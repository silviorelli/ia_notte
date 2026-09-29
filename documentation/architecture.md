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
    |-- app/admin.py     password-protected admin API (/api/admin/*)
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
loading, story (text + audio controls), and error. Every story has its own
URL (`/storia/{id}`, History API): creating or opening a story pushes the
path, browser back/forward and page reloads are handled by a `popstate`
router, and the backend serves the SPA for story deep links so they can be
shared or bookmarked. Outside the home view a header "Indietro" button
returns to the picker. The player is fully
custom around a hidden `<audio>` element: big play/pause button, chapter
chips (one per audio chunk, with a spinner while that chunk's TTS is being
generated and disabled until it is ready; tapping a ready chapter plays it),
a seek slider with time labels, and matching speed and volume sliders.
Speed writes `audioElement.playbackRate` directly, so changes are instant
and never require regenerating audio; speed and volume persist in
`localStorage`. Automatic chapter transitions insert a 1-second pause so
the hand-off sounds natural. Recently generated stories are listed and can
be replayed from the local cache without any Gemini call; the list is
paginated (`GET /api/stories?page=N`, `RECENT_STORIES_PAGE_SIZE` per page)
with "Più recenti" / "Meno recenti" controls below it; on completed
stories the chapter chips seek into the full file using the
`chapter_offsets` stored in the record.

The frontend never sees the Gemini API key; it only talks to the backend.

### Admin area (`static/admin.html`, `app/admin.py`)

`/admin` serves a separate page that asks for the admin password, then lists
every story (character, creation date, requester IP, narration status) with
a delete button. Every `/api/admin/*` route depends on `require_admin`, which
checks the `X-Admin-Password` header against `ADMIN_PASSWORD` (401 if wrong,
503 if unset). `DELETE /api/admin/stories/{id}` removes the record and its
audio files and refuses stories still being narrated (409).

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

`synthesize_chunk` converts one text chunk to raw 16-bit mono PCM,
extracting the samples when the model answers with a WAV file (header and
trailing `C2PA` metadata are dropped).
`split_text` divides the story according to `TTS_CHUNK_PLAN` (per-chunk
character budgets, last value repeating), breaking at paragraph/sentence
boundaries. The first budget is deliberately small (~300 chars, roughly
10 seconds of synthesis) so playback can start quickly.

### Narration orchestrator (`app/narration.py`)

`narrate_story` runs as an asyncio background task spawned by
`POST /api/stories`. It synthesizes all chunks concurrently (bounded by
`TTS_CONCURRENCY`), saves each finished chunk as `<id>.part<n>.wav`,
updates the record's contiguous `chunks_ready` counter and the exact
`parts_done` index list (chunks can finish out of order), and finally
concatenates the PCM into the complete `<id>.wav`, storing per-chapter
start offsets (`chapter_offsets`) and marking the story `ready`. Any failure marks the story `error` (the text stays readable).
Running tasks are tracked in `app.state.narrations` and cancelled at
shutdown; `StoryStore.cleanup` at startup marks stories interrupted by a
restart as errors and deletes leftover part files of completed stories.

### Story cache (`app/storage.py`)

Each story is a JSON record (`<id>.json`, with narration `status`, chunk
counters and the requester's `client_ip`, which only the admin API returns)
plus audio files: `<id>.part<n>.wav` while generating and
`<id>.wav` once complete. Ids are 12-hex-char strings validated by regex on
every lookup, which also prevents path traversal. Records are written via
temp-file-then-rename so pollers never read partial JSON. Corrupted JSON
files are logged and skipped when listing. Records created before chunked
narration are normalized to `status: ready` on read.

## Request flow (story creation)

1. `POST /api/stories` with `{"character": "..."}` (validated by Pydantic).
2. Custom characters (anything not in `PRESET_CHARACTERS`) first pass a
   moderation call (`GeminiClient.moderate_character`, single-word
   ADATTO/NON_ADATTO verdict, fail-closed): unsuitable ones are rejected
   with HTTP 422 and a friendly message before any story or audio is
   generated. Presets skip the check to save quota. As a second layer,
   safety blocks raised by Gemini on the story itself
   (`GeminiBlockedError`) map to the same 422. The character is then
   inserted into the prompt template (`build_story_prompt`).
3. `GeminiClient.generate_story` returns the story text (~10s); the story is
   split into chunks, saved as `generating`, and the response returns
   immediately so the parent can already read the text.
4. `narrate_story` synthesizes chunks in parallel in the background.
5. The frontend polls `GET /api/stories/{id}` (every 2s) and starts playing
   `/api/stories/{id}/audio/0` as soon as `chunks_ready >= 1`, advancing to
   the next part on `ended` (waiting for it if necessary). While generating,
   the polled record also carries `rate_limited: true` whenever the Gemini
   client has recently seen a 429, and the frontend explains the slowdown
   ("troppe richieste al server...") instead of appearing stuck.
6. When the status becomes `ready`, replays use the complete
   `/api/stories/{id}/audio` file (full seeking).

A text-generation failure surfaces as HTTP 502; a missing API key as 503;
a narration failure as `status: error` in the record.

## Deployment

The app ships as a Docker container (see `Dockerfile`, `docker-compose.yml`)
and runs on the OCI ARM instance managed by the separate `infra_relli` repo,
which owns the port opening (security list) and the deploy script
(`infra_relli/scripts/deploy-ia-notte.sh`: rsync of the sources to the
instance, image built there, `docker compose up -d --build`).

```
Internet ──:443 https://ia-notte.relli.it──> caddy (reverse proxy, auto-TLS)
                                               │ host:8082 (not exposed publicly)
                                               ▼
host (OCI ARM instance) ── container ia-notte (uvicorn :8000, non-root user)
                             ├── .env (synced next to the compose file, never in the image)
                             └── named volume stories -> /data/stories (JSON+WAV cache)
```

The Caddy proxy and the public DNS/TLS setup belong to `infra_relli`
(`apps/caddy/`); the host port 8082 is reachable only from the instance
itself, not from the internet.

- Two-stage image: uv installs locked dependencies into `.venv` in a builder
  stage; the runtime stage is `python:3.13-slim` + venv + `app/` + `static/`.
- `STORIES_DIR=/data/stories` is forced by the compose `environment` (it must
  match the volume mount point and win over any value in `.env`).
- **Single uvicorn worker, single replica, by design**: narration tasks and
  rate-limit state live in the process (`app.state.narrations`); scaling out
  would orphan in-flight narrations.
- `stop_grace_period: 60s` lets uvicorn drain long WAV downloads before the
  lifespan hook cancels narrations; `StoryStore.cleanup` self-heals interrupted
  stories at next startup.
- Healthcheck polls `GET /api/config` (cheap, no Gemini call).
