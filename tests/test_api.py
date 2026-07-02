"""API tests with the Gemini client mocked out."""

import wave
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.gemini import GeminiError
from app.main import app
from app.storage import StoryStore

FAKE_STORY = "C'era una volta una storia di prova. Buonanotte."


def make_fake_wav() -> bytes:
    """Build a tiny valid WAV file for test fixtures."""
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(24000)
        wav_file.writeframes(b"\x00\x01" * 240)
    return buffer.getvalue()


class FakeGemini:
    """Stand-in for GeminiClient that returns canned results."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    async def generate_story(self, prompt: str) -> str:
        if self.fail:
            raise GeminiError("simulated failure")
        return FAKE_STORY

    async def synthesize_speech(self, text: str, style_instruction: str) -> bytes:
        return make_fake_wav()

    async def aclose(self) -> None:
        return None


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """TestClient with a fake Gemini backend and an isolated story directory."""
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    with TestClient(app) as test_client:
        app.state.gemini = FakeGemini()
        app.state.store = StoryStore(tmp_path)
        yield test_client


def test_get_config(client: TestClient):
    body = client.get("/api/config").json()
    assert body["characters"] == config.PRESET_CHARACTERS
    assert body["default_playback_rate"] == config.DEFAULT_PLAYBACK_RATE


def test_create_story_and_read_back(client: TestClient):
    response = client.post("/api/stories", json={"character": "Elsa"})
    assert response.status_code == 200
    record = response.json()
    assert record["character"] == "Elsa"
    assert record["story"] == FAKE_STORY
    assert record["audio_url"].endswith("/audio")

    assert client.get(f"/api/stories/{record['id']}").json()["story"] == FAKE_STORY

    audio = client.get(record["audio_url"])
    assert audio.status_code == 200
    assert audio.headers["content-type"] == "audio/wav"
    assert audio.content.startswith(b"RIFF")

    listing = client.get("/api/stories").json()
    assert [entry["id"] for entry in listing] == [record["id"]]


def test_create_story_blank_character_rejected(client: TestClient):
    assert client.post("/api/stories", json={"character": "   "}).status_code == 422
    assert client.post("/api/stories", json={"character": ""}).status_code == 422


def test_create_story_gemini_failure_returns_502(client: TestClient):
    app.state.gemini = FakeGemini(fail=True)
    response = client.post("/api/stories", json={"character": "Minnie"})
    assert response.status_code == 502


def test_create_story_without_api_key_returns_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    assert client.post("/api/stories", json={"character": "Elsa"}).status_code == 503


def test_get_missing_story_returns_404(client: TestClient):
    assert client.get("/api/stories/aaaaaaaaaaaa").status_code == 404
    assert client.get("/api/stories/aaaaaaaaaaaa/audio").status_code == 404


def test_index_page_served(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    assert "IA notte" in response.text
