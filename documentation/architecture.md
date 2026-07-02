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
    |-- app/gemini.py    GeminiClient: text generation + chunk TTS (httpx, async)
    |-- app/narration.py background task: concurrent chunk synthesis
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

`synthesize_chunk` converts one text chunk to raw 16-bit mono PCM.
`split_text` divides the story according to `TTS_CHUNK_PLAN` (per-chunk
character budgets, last value repeating), breaking at paragraph/sentence
boundaries. The first budget is deliberately small (~300 chars, roughly
10 seconds of synthesis) so playback can start quickly.

### Narration orchestrator (`app/narration.py`)

`narrate_story` runs as an asyncio background task spawned by
`POST /api/stories`. It synthesizes all chunks concurrently (bounded by
`TTS_CONCURRENCY`), saves each finished chunk as `<id>.part<n>.wav`,
advances the record's contiguous `chunks_ready` counter, and finally
concatenates the PCM into the complete `<id>.wav`, marking the story
`ready`. Any failure marks the story `error` (the text stays readable).
Running tasks are tracked in `app.state.narrations` and cancelled at
shutdown; `StoryStore.cleanup` at startup marks stories interrupted by a
restart as errors and deletes leftover part files of completed stories.

### Story cache (`app/storage.py`)

Each story is a JSON record (`<id>.json`, with narration `status` and chunk
counters) plus audio files: `<id>.part<n>.wav` while generating and
`<id>.wav` once complete. Ids are 12-hex-char strings validated by regex on
every lookup, which also prevents path traversal. Records are written via
temp-file-then-rename so pollers never read partial JSON. Corrupted JSON
files are logged and skipped when listing. Records created before chunked
narration are normalized to `status: ready` on read.

## Request flow (story creation)

1. `POST /api/stories` with `{"character": "..."}` (validated by Pydantic).
2. The character is inserted into the prompt template (`build_story_prompt`).
3. `GeminiClient.generate_story` returns the story text (~10s); the story is
   split into chunks, saved as `generating`, and the response returns
   immediately so the parent can already read the text.
4. `narrate_story` synthesizes chunks in parallel in the background.
5. The frontend polls `GET /api/stories/{id}` (every 2s) and starts playing
   `/api/stories/{id}/audio/0` as soon as `chunks_ready >= 1`, advancing to
   the next part on `ended` (waiting for it if necessary).
6. When the status becomes `ready`, replays use the complete
   `/api/stories/{id}/audio` file (full seeking).

A text-generation failure surfaces as HTTP 502; a missing API key as 503;
a narration failure as `status: error` in the record.
