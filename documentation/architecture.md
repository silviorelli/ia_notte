# Architecture

## Overview

"IA notte" is a single-page web application backed by a small FastAPI service.
A parent picks (or types) a character; the backend asks Gemini for a bedtime
story, converts it to speech with Gemini TTS, caches both on disk, and returns
them to the browser, which plays the audio with an adjustable playback rate.

```
Browser (static/index.html, vanilla JS + Tailwind CDN)
    |  JSON over HTTP (same origin)
    v
FastAPI app (app/main.py)
    |-- app/config.py    env-based configuration (.env via python-dotenv)
    |-- app/prompts.py   story prompt template + TTS style instruction
    |-- app/gemini.py    GeminiClient: text generation + TTS (httpx, async)
    |-- app/storage.py   StoryStore: JSON + WAV cache on disk (data/stories/)
    v
Google Gemini REST API (generativelanguage.googleapis.com)
```

## Components

### Frontend (`static/index.html`)

Single mobile-first page with four views toggled by JS: character picker,
loading, story (text + audio controls), and error. The playback-speed slider
writes `audioElement.playbackRate` directly, so speed changes are instant and
never require regenerating audio. The chosen speed persists in
`localStorage`. Recently generated stories are listed and can be replayed
from the local cache without any Gemini call.

The frontend never sees the Gemini API key; it only talks to the backend.

### Backend (`app/main.py`)

FastAPI application with a lifespan that creates two shared resources:
a `GeminiClient` (one httpx connection pool) and a `StoryStore`. Static files
are mounted at `/` after the API routes. Endpoints are documented in
`documentation/api.json` (OpenAPI, generated from the app itself).

### Gemini client (`app/gemini.py`)

All Gemini calls go through `_generate_content`, which implements:

- retry with exponential backoff on transient errors (429/5xx, network),
  up to 3 attempts per model;
- model fallback: models are configured as an ordered list; a 404 (model
  unavailable) or exhausted retries move to the next model;
- fail-fast on non-retryable client errors (e.g. 400/403).

TTS output is raw 16-bit mono PCM (base64). Long stories are split at
paragraph/sentence boundaries into chunks below `TTS_CHUNK_MAX_CHARS`; each
chunk is synthesized separately (with the style instruction prepended) and
the PCM streams are concatenated, then wrapped in a single WAV container
with the stdlib `wave` module.

### Story cache (`app/storage.py`)

Each story is a pair of files in `data/stories/`: `<id>.json` (record with
id, character, story text, ISO timestamp) and `<id>.wav` (narration).
Ids are 12-hex-char strings validated by regex on every lookup, which also
prevents path traversal. Corrupted JSON files are logged and skipped when
listing.

## Request flow (story creation)

1. `POST /api/stories` with `{"character": "..."}` (validated by Pydantic).
2. The character is inserted into the prompt template (`build_story_prompt`).
3. `GeminiClient.generate_story` returns the story text.
4. `GeminiClient.synthesize_speech` returns WAV audio of the narration.
5. `StoryStore.save` persists both; the record (with `audio_url`) is returned.
6. The frontend sets the audio element source to `/api/stories/{id}/audio`.

Failures in steps 3-4 surface as HTTP 502 with a user-friendly Italian
message; a missing API key surfaces as HTTP 503.
