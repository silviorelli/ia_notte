"""Tests for the background narration orchestrator."""

import asyncio
import wave
from io import BytesIO
from pathlib import Path

import pytest

from app.gemini import GeminiError
from app.narration import narrate_story
from app.storage import STATUS_ERROR, STATUS_READY, StoryStore

pytestmark = pytest.mark.anyio


class FakeGemini:
    """Synthesizer stub whose PCM output is the chunk text itself."""

    def __init__(self, delays: dict[str, float] | None = None, fail_on: str | None = None):
        self.delays = delays or {}
        self.fail_on = fail_on

    async def synthesize_chunk(self, text: str, style_instruction: str) -> tuple[bytes, int]:
        await asyncio.sleep(self.delays.get(text, 0))
        if text == self.fail_on:
            raise GeminiError("simulated TTS failure")
        return text.encode(), 24000


def read_pcm(wav_bytes: bytes) -> bytes:
    with wave.open(BytesIO(wav_bytes)) as wav_file:
        return wav_file.readframes(wav_file.getnframes())


async def test_narrate_story_preserves_order_despite_completion_order(tmp_path: Path):
    store = StoryStore(tmp_path)
    chunks = ["1111", "2222", "3333"]
    record = store.save("Elsa", " ".join(chunks), chunks_total=len(chunks))
    gemini = FakeGemini(delays={"1111": 0.05, "2222": 0.0, "3333": 0.02})

    await narrate_story(gemini, store, record["id"], chunks, "stile ", concurrency=3)

    loaded = store.get(record["id"])
    assert loaded["status"] == STATUS_READY
    assert loaded["chunks_ready"] == 3
    assert read_pcm(store.audio_path(record["id"]).read_bytes()) == b"111122223333"
    for index, chunk in enumerate(chunks):
        assert read_pcm(store.part_path(record["id"], index).read_bytes()) == chunk.encode()


async def test_narrate_story_marks_error_on_failure(tmp_path: Path):
    store = StoryStore(tmp_path)
    chunks = ["1111", "2222", "3333"]
    record = store.save("Elsa", " ".join(chunks), chunks_total=len(chunks))
    gemini = FakeGemini(fail_on="2222")

    await narrate_story(gemini, store, record["id"], chunks, "stile ", concurrency=2)

    loaded = store.get(record["id"])
    assert loaded["status"] == STATUS_ERROR
    assert store.audio_path(record["id"]) is None
