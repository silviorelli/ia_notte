"""FastAPI application: story generation endpoints and static frontend."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import config
from app.gemini import GeminiClient, GeminiError, GeminiSettings, split_text
from app.narration import narrate_story
from app.prompts import TTS_STYLE_INSTRUCTION, build_story_prompt
from app.storage import StoryStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class StoryRequest(BaseModel):
    """Request body for story creation."""

    character: str = Field(min_length=1, max_length=80)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Create shared resources at startup and release them at shutdown."""
    if not config.GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY is not set: story generation will return 503")
    application.state.gemini = GeminiClient(
        GeminiSettings(
            api_key=config.GEMINI_API_KEY,
            text_models=config.TEXT_MODELS,
            tts_models=config.TTS_MODELS,
            tts_voice=config.TTS_VOICE,
            language_code=config.TTS_LANGUAGE,
        )
    )
    application.state.store = StoryStore(config.STORIES_DIR)
    application.state.store.cleanup()
    application.state.narrations = set()
    yield
    for task in application.state.narrations:
        task.cancel()
    await asyncio.gather(*application.state.narrations, return_exceptions=True)
    await application.state.gemini.aclose()


app = FastAPI(title="IA notte", version="0.2.0", lifespan=lifespan)


def _public_record(record: dict) -> dict:
    """Add the audio URL to a stored record before returning it to the client."""
    return {**record, "audio_url": f"/api/stories/{record['id']}/audio"}


@app.get("/api/config")
def get_config() -> dict:
    """Return frontend configuration: preset characters and default speed."""
    return {
        "characters": config.PRESET_CHARACTERS,
        "default_playback_rate": config.DEFAULT_PLAYBACK_RATE,
    }


@app.post("/api/stories")
async def create_story(payload: StoryRequest, request: Request) -> dict:
    """Generate a story and start its narration in the background.

    Returns as soon as the story text is ready; audio chunks are synthesized
    concurrently by a background task and exposed via the record's
    ``chunks_ready`` counter and the part audio endpoint.

    Raises:
        HTTPException: 503 if the API key is missing, 502 if generation fails.
    """
    if not config.GEMINI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Chiave API non configurata: imposta GEMINI_API_KEY nel file .env",
        )
    character = payload.character.strip()
    if not character:
        raise HTTPException(status_code=422, detail="Il nome del personaggio è vuoto")
    gemini: GeminiClient = request.app.state.gemini
    store: StoryStore = request.app.state.store
    try:
        story = await gemini.generate_story(build_story_prompt(character))
    except GeminiError as exc:
        logger.error("Story generation failed for %r: %s", character, exc)
        raise HTTPException(
            status_code=502,
            detail="La generazione non è riuscita, riprova tra qualche istante",
        ) from exc
    chunks = split_text(story, config.TTS_CHUNK_PLAN)
    record = store.save(character, story, chunks_total=len(chunks))
    task = asyncio.create_task(
        narrate_story(
            gemini, store, record["id"], chunks, TTS_STYLE_INSTRUCTION, config.TTS_CONCURRENCY
        )
    )
    request.app.state.narrations.add(task)
    task.add_done_callback(request.app.state.narrations.discard)
    return _public_record(record)


@app.get("/api/stories")
def list_stories(request: Request) -> list[dict]:
    """List the most recently generated stories, newest first."""
    store: StoryStore = request.app.state.store
    return store.list_recent(config.RECENT_STORIES_LIMIT)


@app.get("/api/stories/{story_id}")
def get_story(story_id: str, request: Request) -> dict:
    """Return a cached story record.

    While narration is in progress the response also carries a
    ``rate_limited`` flag so the frontend can explain slowdowns caused by
    API quota throttling.

    Raises:
        HTTPException: 404 if the story does not exist.
    """
    store: StoryStore = request.app.state.store
    gemini: GeminiClient = request.app.state.gemini
    record = store.get(story_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Storia non trovata")
    if record["status"] == "generating" and gemini.is_rate_limited():
        record["rate_limited"] = True
    return _public_record(record)


@app.get("/api/stories/{story_id}/audio")
def get_story_audio(story_id: str, request: Request) -> FileResponse:
    """Stream the complete WAV narration of a cached story.

    Raises:
        HTTPException: 404 if the audio does not exist (yet).
    """
    store: StoryStore = request.app.state.store
    path = store.audio_path(story_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Audio non trovato")
    return FileResponse(path, media_type="audio/wav")


@app.get("/api/stories/{story_id}/audio/{part}")
def get_story_audio_part(story_id: str, part: int, request: Request) -> FileResponse:
    """Stream one narration chunk of a story being generated.

    Raises:
        HTTPException: 404 if the part does not exist (yet).
    """
    store: StoryStore = request.app.state.store
    path = store.part_path(story_id, part)
    if path is None:
        raise HTTPException(status_code=404, detail="Blocco audio non trovato")
    return FileResponse(path, media_type="audio/wav")


app.mount("/", StaticFiles(directory=config.STATIC_DIR, html=True), name="static")
