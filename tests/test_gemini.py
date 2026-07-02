"""Tests for the Gemini client: retries, fallbacks, chunking and WAV output."""

import httpx
import pytest

from app.gemini import GeminiClient, GeminiError, GeminiSettings, _split_text
from tests.conftest import audio_response, text_response

pytestmark = pytest.mark.anyio


def make_client(handler, text_models=("model-a",), tts_models=("tts-a",)) -> GeminiClient:
    """Build a GeminiClient backed by a mock transport."""
    settings = GeminiSettings(
        api_key="test-key",
        text_models=text_models,
        tts_models=tts_models,
        tts_voice="Sulafat",
        language_code="it-IT",
        retry_base_delay=0.0,
    )
    return GeminiClient(settings, transport=httpx.MockTransport(handler))


async def test_generate_story_returns_text():
    client = make_client(lambda request: text_response("C'era una volta una storia."))
    story = await client.generate_story("prompt")
    assert story == "C'era una volta una storia."
    await client.aclose()


async def test_generate_story_retries_on_server_error():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if len(calls) < 3:
            return httpx.Response(500, text="boom")
        return text_response("Storia dopo i retry.")

    client = make_client(handler)
    story = await client.generate_story("prompt")
    assert story == "Storia dopo i retry."
    assert len(calls) == 3
    await client.aclose()


async def test_generate_story_falls_back_on_missing_model():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if "model-a" in request.url.path:
            return httpx.Response(404, text="not found")
        return text_response("Storia dal modello di riserva.")

    client = make_client(handler, text_models=("model-a", "model-b"))
    story = await client.generate_story("prompt")
    assert story == "Storia dal modello di riserva."
    assert calls == [
        "/v1beta/models/model-a:generateContent",
        "/v1beta/models/model-b:generateContent",
    ]
    await client.aclose()


async def test_generate_story_fails_fast_on_client_error():
    client = make_client(lambda request: httpx.Response(400, text="bad request"))
    with pytest.raises(GeminiError, match="HTTP 400"):
        await client.generate_story("prompt")
    await client.aclose()


async def test_generate_story_raises_after_all_retries():
    client = make_client(lambda request: httpx.Response(503, text="unavailable"))
    with pytest.raises(GeminiError, match="All models failed"):
        await client.generate_story("prompt")
    await client.aclose()


async def test_synthesize_speech_returns_wav():
    pcm = b"\x01\x02" * 100

    def handler(request: httpx.Request) -> httpx.Response:
        return audio_response(pcm)

    client = make_client(handler)
    wav = await client.synthesize_speech("Una piccola storia.", "Leggi piano. ")
    assert wav.startswith(b"RIFF")
    assert b"WAVE" in wav[:16]
    assert pcm in wav
    await client.aclose()


async def test_synthesize_speech_concatenates_chunks():
    requests_seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(request.read())
        return audio_response(b"\x0a\x0b" * 10)

    client = make_client(handler)
    long_text = "\n\n".join(f"Paragrafo numero {i}. " + "parola " * 300 for i in range(4))
    wav = await client.synthesize_speech(long_text, "Leggi piano. ")
    assert len(requests_seen) > 1
    assert wav.startswith(b"RIFF")
    assert all(b"Leggi piano." in body for body in requests_seen)
    await client.aclose()


def test_split_text_short_text_is_single_chunk():
    assert _split_text("breve", 100) == ["breve"]


def test_split_text_respects_max_chars_and_keeps_content():
    text = "\n\n".join(f"Frase {i}. " + "parola " * 80 for i in range(6))
    chunks = _split_text(text, 1000)
    assert all(len(chunk) <= 1000 for chunk in chunks)
    assert "".join(chunks).replace("\n", " ").count("parola") == text.count("parola")


def test_split_text_hard_splits_oversized_sentence():
    text = "a" * 2500
    chunks = _split_text(text, 1000)
    assert all(len(chunk) <= 1000 for chunk in chunks)
    assert "".join(chunks) == text
