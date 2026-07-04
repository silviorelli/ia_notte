"""Tests for the Gemini client: retries, fallbacks, chunk synthesis and splitting."""

import httpx
import pytest

from app.gemini import GeminiBlockedError, GeminiClient, GeminiError, GeminiSettings, split_text
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


async def test_generate_story_retries_rate_limit_with_server_hint():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if len(calls) == 1:
            return httpx.Response(
                429,
                json={"error": {"details": [{"retryDelay": "0s"}]}},
            )
        return text_response("Storia dopo il rate limit.")

    client = make_client(handler)
    assert client.is_rate_limited() is False
    story = await client.generate_story("prompt")
    assert story == "Storia dopo il rate limit."
    assert len(calls) == 2
    assert client.is_rate_limited() is True
    await client.aclose()


async def test_rate_limit_hits_do_not_consume_regular_attempts():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if len(calls) <= 4:
            return httpx.Response(429, json={"error": {"details": [{"retryDelay": "0s"}]}})
        return text_response("Storia con quota al minuto esaurita.")

    client = make_client(handler)
    story = await client.generate_story("prompt")
    assert story == "Storia con quota al minuto esaurita."
    assert len(calls) == 5
    await client.aclose()


async def test_daily_quota_falls_back_to_next_model_without_retrying():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if "model-a" in request.url.path:
            return httpx.Response(
                429,
                json={
                    "error": {
                        "details": [
                            {
                                "violations": [
                                    {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}
                                ]
                            }
                        ]
                    }
                },
            )
        return text_response("Storia dal modello di riserva.")

    client = make_client(handler, text_models=("model-a", "model-b"))
    story = await client.generate_story("prompt")
    assert story == "Storia dal modello di riserva."
    assert len(calls) == 2
    await client.aclose()


async def test_generate_story_raises_after_all_retries():
    client = make_client(lambda request: httpx.Response(503, text="unavailable"))
    with pytest.raises(GeminiError, match="All models failed"):
        await client.generate_story("prompt")
    await client.aclose()


async def test_generate_story_raises_blocked_on_prompt_feedback():
    client = make_client(
        lambda request: httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}})
    )
    with pytest.raises(GeminiBlockedError):
        await client.generate_story("prompt")
    await client.aclose()


async def test_generate_story_raises_blocked_on_safety_finish():
    client = make_client(
        lambda request: httpx.Response(
            200,
            json={"candidates": [{"finishReason": "SAFETY", "content": {"parts": []}}]},
        )
    )
    with pytest.raises(GeminiBlockedError):
        await client.generate_story("prompt")
    await client.aclose()


@pytest.mark.parametrize(
    ("verdict", "allowed"),
    [
        ("ADATTO", True),
        ("adatto", True),
        ("NON_ADATTO", False),
        ("Non adatto.", False),
        ("boh, dipende", False),
    ],
)
async def test_moderate_character_verdicts(verdict: str, allowed: bool):
    client = make_client(lambda request: text_response(verdict))
    assert await client.moderate_character("prompt di moderazione") is allowed
    await client.aclose()


async def test_moderate_character_rejects_on_safety_block():
    client = make_client(
        lambda request: httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}})
    )
    assert await client.moderate_character("prompt di moderazione") is False
    await client.aclose()


async def test_synthesize_chunk_returns_pcm_and_rate():
    pcm = b"\x01\x02" * 100
    requests_seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(request.read())
        return audio_response(pcm, rate=16000)

    client = make_client(handler)
    result_pcm, rate = await client.synthesize_chunk("Una piccola storia.", "Leggi piano. ")
    assert result_pcm == pcm
    assert rate == 16000
    assert b"Leggi piano." in requests_seen[0]
    await client.aclose()


def test_split_text_short_text_is_single_chunk():
    assert split_text("breve", (100, 500)) == ["breve"]


def test_split_text_respects_per_chunk_budgets():
    text = "\n\n".join("Frase numero uno. " + "parola " * 60 for _ in range(6))
    chunks = split_text(text, (300, 600, 1200))
    budgets = [300, 600] + [1200] * (len(chunks) - 2)
    assert len(chunks) > 2
    assert all(len(chunk) <= budget for chunk, budget in zip(chunks, budgets, strict=True))
    assert " ".join(chunks).replace("\n", " ").count("parola") == text.count("parola")


def test_split_text_hard_splits_oversized_sentence():
    text = "a" * 2500
    chunks = split_text(text, (1000,))
    assert all(len(chunk) <= 1000 for chunk in chunks)
    assert "".join(chunks) == text
