"""API tests with the Gemini client mocked out."""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.gemini import GeminiError
from app.main import app
from app.storage import StoryStore

FAKE_STORY = "C'era una volta una storia di prova. Buonanotte."
FAKE_PCM = b"\x00\x01" * 240


class FakeGemini:
    """Stand-in for GeminiClient that returns canned results."""

    def __init__(self, fail_tts: bool = False) -> None:
        self.fail_tts = fail_tts

    async def generate_story(self, prompt: str) -> str:
        return FAKE_STORY

    async def synthesize_chunk(self, text: str, style_instruction: str) -> tuple[bytes, int]:
        if self.fail_tts:
            raise GeminiError("simulated failure")
        return FAKE_PCM, 24000

    async def aclose(self) -> None:
        return None


class FailingTextGemini(FakeGemini):
    """Fake whose text generation always fails."""

    async def generate_story(self, prompt: str) -> str:
        raise GeminiError("simulated text failure")


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """TestClient with a fake Gemini backend and an isolated story directory."""
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    with TestClient(app) as test_client:
        app.state.gemini = FakeGemini()
        app.state.store = StoryStore(tmp_path)
        yield test_client


def wait_until_settled(client: TestClient, story_id: str, timeout: float = 5.0) -> dict:
    """Poll the story record until narration finishes or fails."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = client.get(f"/api/stories/{story_id}").json()
        if record["status"] != "generating":
            return record
        time.sleep(0.02)
    raise AssertionError("narration did not settle in time")


def test_get_config(client: TestClient):
    body = client.get("/api/config").json()
    assert body["characters"] == config.PRESET_CHARACTERS
    assert body["default_playback_rate"] == config.DEFAULT_PLAYBACK_RATE


def test_create_story_returns_text_then_audio_becomes_ready(client: TestClient):
    response = client.post("/api/stories", json={"character": "Elsa"})
    assert response.status_code == 200
    record = response.json()
    assert record["character"] == "Elsa"
    assert record["story"] == FAKE_STORY
    assert record["status"] == "generating"
    assert record["chunks_total"] >= 1
    assert record["audio_url"].endswith("/audio")

    settled = wait_until_settled(client, record["id"])
    assert settled["status"] == "ready"
    assert settled["chunks_ready"] == settled["chunks_total"]

    audio = client.get(settled["audio_url"])
    assert audio.status_code == 200
    assert audio.headers["content-type"] == "audio/wav"
    assert audio.content.startswith(b"RIFF")

    part = client.get(f"/api/stories/{record['id']}/audio/0")
    assert part.status_code == 200
    assert part.content.startswith(b"RIFF")

    listing = client.get("/api/stories").json()
    assert [entry["id"] for entry in listing] == [record["id"]]
    assert listing[0]["status"] == "ready"


def test_story_is_split_into_multiple_chunks(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "TTS_CHUNK_PLAN", (12, 24))
    record = client.post("/api/stories", json={"character": "Elsa"}).json()
    assert record["chunks_total"] > 1

    settled = wait_until_settled(client, record["id"])
    assert settled["status"] == "ready"
    for index in range(settled["chunks_total"]):
        part = client.get(f"/api/stories/{record['id']}/audio/{index}")
        assert part.status_code == 200


def test_tts_failure_marks_story_error_but_keeps_text(client: TestClient):
    app.state.gemini = FakeGemini(fail_tts=True)
    record = client.post("/api/stories", json={"character": "Minnie"}).json()
    assert record["story"] == FAKE_STORY

    settled = wait_until_settled(client, record["id"])
    assert settled["status"] == "error"
    assert client.get(settled["audio_url"]).status_code == 404


def test_text_failure_returns_502(client: TestClient):
    app.state.gemini = FailingTextGemini()
    response = client.post("/api/stories", json={"character": "Minnie"})
    assert response.status_code == 502


def test_create_story_blank_character_rejected(client: TestClient):
    assert client.post("/api/stories", json={"character": "   "}).status_code == 422
    assert client.post("/api/stories", json={"character": ""}).status_code == 422


def test_create_story_without_api_key_returns_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    assert client.post("/api/stories", json={"character": "Elsa"}).status_code == 503


def test_get_missing_story_returns_404(client: TestClient):
    assert client.get("/api/stories/aaaaaaaaaaaa").status_code == 404
    assert client.get("/api/stories/aaaaaaaaaaaa/audio").status_code == 404
    assert client.get("/api/stories/aaaaaaaaaaaa/audio/0").status_code == 404


def test_index_page_served(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    assert "IA notte" in response.text
