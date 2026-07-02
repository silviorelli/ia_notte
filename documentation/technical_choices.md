# Technical Choices

## Stack

- **FastAPI + uvicorn**: required by the project brief; async endpoints fit
  the long-running Gemini calls without blocking the event loop.
- **uv**: package/venv management, per repo guidelines (AGENTS.md).
- **Vanilla JS + Tailwind via CDN**: a single HTML file, no build step.
  Trade-off: the Tailwind CDN requires an internet connection at page load,
  acceptable for a home-use app that needs internet for Gemini anyway.

## Gemini integration

- **Direct REST calls with httpx** instead of the `google-genai` SDK: the two
  calls needed (`generateContent` for text and for TTS) are trivial JSON
  posts; httpx keeps the dependency small, makes the retry/fallback logic
  explicit, and allows mocking in tests with the built-in
  `httpx.MockTransport` (no extra test dependency).
- **Model fallback lists**: TTS model naming has churned across releases
  (`gemini-2.5-flash-tts`, `gemini-2.5-flash-preview-tts`,
  `gemini-3.1-flash-tts-preview`), so `GEMINI_TEXT_MODEL` and
  `GEMINI_TTS_MODEL` accept comma-separated lists tried in order; a 404
  moves to the next model. This makes the app resilient to model renames
  without code changes.
- **Retry policy**: 3 attempts per model, exponential backoff (1s, 2s),
  retrying only 429/5xx/network errors. Non-retryable 4xx fail immediately
  (a bad key or payload will not improve by retrying). Required by the brief
  because the TTS endpoint occasionally returns 500.
- **Voice**: `Sulafat` by default (documented as a warm voice), configurable
  via `GEMINI_TTS_VOICE`. Language fixed to `it-IT` via `GEMINI_TTS_LANGUAGE`.

## Audio format

- Gemini TTS returns raw 16-bit mono PCM at 24 kHz. The backend wraps it in
  a WAV container with the stdlib `wave` module: zero dependencies and every
  browser can play and seek it. Trade-off: WAV is large (~2.8 MB/min), fine
  on a home network; MP3 would need ffmpeg/lame, not worth the dependency.
- Long texts are chunked below 3500 chars at paragraph/sentence boundaries
  and the PCM concatenated before wrapping, so arbitrarily long stories
  produce one seamless audio file.
- Playback speed is a pure frontend concern (`audioElement.playbackRate`),
  so one generated audio serves every speed in the 0.6x-1.0x range.

## Caching

- Flat-file cache (`data/stories/`, JSON + WAV per story) instead of a
  database: family-scale data volume, human-inspectable, trivially safe to
  delete. Listing reads all JSON files and sorts in memory, which is fine
  for the 20-item recent list.

## Security

- API key only in `.env` (gitignored), read server-side; the browser never
  receives it and all Gemini traffic goes through the backend.
- Story ids validated against `^[0-9a-f]{12}$` before any filesystem access,
  preventing path traversal.
- Request bodies validated with Pydantic (character: 1-80 chars).

## Testing

- pytest; all external calls mocked (`httpx.MockTransport` for the Gemini
  client, a fake client object for API tests). Async tests run through the
  anyio pytest plugin already shipped as an httpx/starlette dependency.
