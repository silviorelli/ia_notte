"""Async client for the Gemini REST API: story text generation and TTS.

All calls go through ``_generate_content``, which retries transient errors
(429/5xx) with exponential backoff and falls back to the next model in the
configured list when a model is unavailable (404) or keeps failing.
"""

import asyncio
import base64
import io
import logging
import re
import time
import wave
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
MAX_ATTEMPTS = 3
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
TTS_CHUNK_MAX_CHARS = 3500
DEFAULT_SAMPLE_RATE = 24000
_RATE_PATTERN = re.compile(r"rate=(\d+)")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
_PARAGRAPH_BOUNDARY = re.compile(r"\n\s*\n")


class GeminiError(Exception):
    """Raised when a Gemini API call fails after all retries and fallbacks."""


@dataclass(frozen=True)
class GeminiSettings:
    """Connection and model configuration for :class:`GeminiClient`.

    Args:
        api_key: Google Gemini API key.
        text_models: Text models to try in order for story generation.
        tts_models: TTS models to try in order for speech synthesis.
        tts_voice: Prebuilt voice name (e.g. ``Sulafat``).
        language_code: BCP-47 language code for TTS (e.g. ``it-IT``).
        retry_base_delay: Base delay in seconds for exponential backoff.
    """

    api_key: str
    text_models: tuple[str, ...]
    tts_models: tuple[str, ...]
    tts_voice: str
    language_code: str
    retry_base_delay: float = 1.0


class GeminiClient:
    """Thin async wrapper around the Gemini ``generateContent`` endpoint."""

    def __init__(
        self,
        settings: GeminiSettings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Create the client and its underlying HTTP connection pool.

        Args:
            settings: Model and retry configuration.
            transport: Optional httpx transport, used by tests for mocking.
        """
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=API_BASE_URL,
            timeout=httpx.Timeout(300.0, connect=10.0),
            transport=transport,
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP connection pool."""
        await self._client.aclose()

    async def generate_story(self, prompt: str) -> str:
        """Generate a story from the given prompt.

        Args:
            prompt: Complete prompt for the text model.

        Returns:
            The generated story text.

        Raises:
            GeminiError: If all models fail or the response contains no text.
        """
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        data = await self._generate_content(self._settings.text_models, payload)
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(part.get("text", "") for part in parts).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise GeminiError(f"Unexpected text response shape: {exc}") from exc
        if not text:
            raise GeminiError("Model returned an empty story")
        return text

    async def synthesize_speech(self, text: str, style_instruction: str) -> bytes:
        """Convert story text to spoken audio.

        Long texts are split into chunks at paragraph/sentence boundaries;
        the resulting PCM streams are concatenated into a single WAV file.

        Args:
            text: Story text to read aloud.
            style_instruction: Reading-style instruction prepended to each chunk.

        Returns:
            WAV audio bytes (16-bit mono PCM).

        Raises:
            GeminiError: If all models fail or a response contains no audio.
        """
        pcm = bytearray()
        sample_rate = DEFAULT_SAMPLE_RATE
        chunks = _split_text(text, TTS_CHUNK_MAX_CHARS)
        for index, chunk in enumerate(chunks, start=1):
            logger.info(
                "Synthesizing audio chunk %d/%d (%d chars), this can take a few minutes",
                index,
                len(chunks),
                len(chunk),
            )
            payload = {
                "contents": [{"parts": [{"text": style_instruction + chunk}]}],
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {
                        "languageCode": self._settings.language_code,
                        "voiceConfig": {
                            "prebuiltVoiceConfig": {"voiceName": self._settings.tts_voice}
                        },
                    },
                },
            }
            data = await self._generate_content(self._settings.tts_models, payload)
            try:
                inline = data["candidates"][0]["content"]["parts"][0]["inlineData"]
                pcm += base64.b64decode(inline["data"])
            except (KeyError, IndexError, TypeError) as exc:
                raise GeminiError(f"Unexpected TTS response shape: {exc}") from exc
            sample_rate = _parse_sample_rate(inline.get("mimeType", ""))
        return _pcm_to_wav(bytes(pcm), sample_rate)

    async def _generate_content(self, models: tuple[str, ...], payload: dict) -> dict:
        """POST to ``generateContent``, with retries and model fallback.

        Args:
            models: Models to try in order.
            payload: JSON request body.

        Returns:
            Parsed JSON response of the first successful call.

        Raises:
            GeminiError: On non-retryable errors or when everything fails.
        """
        last_error: Exception | None = None
        for model in models:
            for attempt in range(1, MAX_ATTEMPTS + 1):
                started = time.monotonic()
                try:
                    response = await self._client.post(
                        f"/models/{model}:generateContent",
                        json=payload,
                        headers={"x-goog-api-key": self._settings.api_key},
                    )
                except httpx.HTTPError as exc:
                    last_error = exc
                    logger.error(
                        "Request to %s failed (attempt %d/%d): %s",
                        model,
                        attempt,
                        MAX_ATTEMPTS,
                        exc,
                    )
                else:
                    if response.status_code == 200:
                        logger.info("%s responded in %.1fs", model, time.monotonic() - started)
                        return response.json()
                    last_error = GeminiError(
                        f"{model} returned HTTP {response.status_code}: {response.text[:300]}"
                    )
                    if response.status_code == 404:
                        logger.error("Model %s not available, trying next fallback", model)
                        break
                    logger.error(
                        "Gemini error from %s (attempt %d/%d): HTTP %d",
                        model,
                        attempt,
                        MAX_ATTEMPTS,
                        response.status_code,
                    )
                    if response.status_code not in RETRYABLE_STATUS_CODES:
                        raise last_error
                if attempt < MAX_ATTEMPTS:
                    await asyncio.sleep(self._settings.retry_base_delay * 2 ** (attempt - 1))
        raise GeminiError(f"All models failed ({', '.join(models)})") from last_error


def _split_text(text: str, max_chars: int) -> list[str]:
    """Split text into chunks of at most ``max_chars`` characters.

    Prefers paragraph boundaries, then sentence boundaries, then a hard cut
    for pathological single sentences.

    Args:
        text: Text to split.
        max_chars: Maximum chunk length in characters.

    Returns:
        Non-empty list of chunks in original order.
    """
    if len(text) <= max_chars:
        return [text]
    pieces: list[str] = []
    for paragraph in filter(str.strip, _PARAGRAPH_BOUNDARY.split(text)):
        if len(paragraph) <= max_chars:
            pieces.append(paragraph)
            continue
        for sentence in _SENTENCE_BOUNDARY.split(paragraph):
            pieces.extend(sentence[i : i + max_chars] for i in range(0, len(sentence), max_chars))
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current}\n\n{piece}" if current else piece
        if len(candidate) > max_chars:
            chunks.append(current)
            current = piece
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _parse_sample_rate(mime_type: str) -> int:
    """Extract the PCM sample rate from a mime type like ``audio/L16;rate=24000``.

    Args:
        mime_type: Mime type string from the API response.

    Returns:
        Sample rate in Hz, or :data:`DEFAULT_SAMPLE_RATE` if absent.
    """
    match = _RATE_PATTERN.search(mime_type)
    return int(match.group(1)) if match else DEFAULT_SAMPLE_RATE


def _pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    """Wrap raw 16-bit mono PCM data in a WAV container.

    Args:
        pcm: Raw little-endian 16-bit mono PCM bytes.
        sample_rate: Sample rate in Hz.

    Returns:
        Complete WAV file bytes.
    """
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm)
    return buffer.getvalue()
