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
  `gemini-3.1-flash-tts-preview`, `gemini-3.8-flash-tts`), so `GEMINI_TEXT_MODEL` and
  `GEMINI_TTS_MODEL` accept comma-separated lists tried in order; a 404
  moves to the next model. This makes the app resilient to model renames
  without code changes.
- **TTS model choice and reading style**: the style instruction and the
  text to speak go in one prompt, split into `### NOTE DI REGIA` and
  `### TRASCRIZIONE` sections (the 3.x models reject `systemInstruction`
  with "Developer instruction is not enabled for this model"). Without the
  sections, 3.x models read the instruction aloud. With them, a comparison
  that transcribed each output showed `gemini-3.1-flash-tts-preview`
  applying the calm style (about 115 words/min against about 145 unstyled)
  with no added words; `gemini-3.8-flash-tts` read exactly but only slightly
  slower; `gemini-3.8-flash-lite-tts` sometimes invented extra sentences, so
  it is not used. Default order: `gemini-3.1-flash-tts-preview`, then
  `gemini-3.8-flash-tts`.
- **Retry policy**: 3 attempts per model with exponential backoff (1s, 2s)
  for 5xx/network errors. Non-retryable 4xx fail immediately (a bad key or
  payload will not improve by retrying). Rate limits (429) get their own
  budget of 4 extra waits per model that do not consume regular attempts:
  free-tier keys allow only 3 requests/minute per TTS model
  (`GenerateRequestsPerMinutePerProjectPerModel-FreeTier`), so the client
  honors the server-suggested delay (`RetryInfo.retryDelay` in the body or
  `Retry-After` header, floored at 5s, capped at 60s) and rides out the
  minute window instead of burning attempts. On a free-tier key a 5-chunk
  story therefore completes in a few minutes despite the quota; model
  fallback remains the last resort so the voice stays consistent.
- **Voice**: `Sulafat` by default (documented as a warm voice), configurable
  via `GEMINI_TTS_VOICE`. Language fixed to `it-IT` via `GEMINI_TTS_LANGUAGE`.

## Audio format and progressive narration

- Gemini TTS returns 16-bit mono PCM at 24 kHz: older models as bare PCM
  (`audio/L16;rate=...`), 3.x models as a complete WAV file (`audio/wav`)
  that ends with a `C2PA` content-credentials chunk. `_decode_audio` reads
  WAV payloads with the stdlib `wave` module, which keeps only the `fmt` and
  `data` chunks; treating the whole payload as samples played its header
  and the C2PA chunk as a crackle at every chapter boundary. The backend
  then wraps the PCM in its own WAV container with `wave`: zero dependencies
  and every browser can play and seek it. Trade-off: WAV is large (~2.8 MB/min), fine
  on a home network; MP3 would need ffmpeg/lame, not worth the dependency.
- The TTS models expose only `generateContent` (no `streamGenerateContent`,
  verified via ListModels), and synthesis runs at roughly 2.5x real time
  (~105s for a whole 4-minute story). To cut perceived latency the story is
  split per `TTS_CHUNK_PLAN` (default 300,600,1200 chars: the last value
  repeats) and chunks are synthesized concurrently (`TTS_CONCURRENCY`,
  default 3) by a background task. The small first chunk is ready in ~10s,
  so playback starts while the rest is still generating; growing budgets
  keep later chunks ready before the player needs them.
- The frontend polls the record every 2s and plays part files sequentially
  through one audio element, with a deliberate 1-second pause between
  automatic chapter transitions (an immediate hand-off sounded unnatural).
  Chunks double as user-facing "chapters": the record exposes the exact
  `parts_done` indices (chunks finish out of order under concurrency) so
  each chapter chip can show a spinner until its own TTS is done and stay
  disabled meanwhile. Once narration completes, the parts are concatenated
  into a single WAV used for replays, and `chapter_offsets` (start second
  of each chapter, derived from PCM lengths) lets chapter selection work on
  the full file as plain seeks. Part files are cleaned up at next startup
  rather than at finalize time so a client mid-playback never loses its
  source.
- Playback speed is a pure frontend concern (`audioElement.playbackRate`),
  so one generated audio serves every speed in the 0.8x-1.4x range.

## Child-safety moderation

- Custom characters are vetted by a dedicated Gemini call before story
  generation (user's explicit choice over a prompt-only safeguard): the
  moderation prompt asks for a single-word ADATTO/NON_ADATTO verdict at
  temperature 0, states prioritized rules (real people tied to pornography,
  crimes, dictatorships etc. are always unsuitable; "when in doubt, reject")
  and includes few-shot examples, with instructions declared to take
  priority over anything in the proposal (basic prompt-injection
  resistance). Verdict parsing is strict: only the exact token ADATTO
  approves; prose like "non è adatto", unclear verdicts or safety blocks
  all reject (fail closed) — a lesson from v1, where a substring check
  ("ADATTO" in reply) turned "non è adatto" into an approval and let
  real-person characters slip through. Costs one extra text request and
  ~1-2s per custom story; preset characters skip the check entirely, so
  the most common path (kids tapping presets) spends nothing.
- Belt and suspenders: `promptFeedback.blockReason` and
  `finishReason: SAFETY` on the story call raise `GeminiBlockedError`,
  which the API maps to the same friendly 422 instead of a generic error.

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

## Admin area

- **Single shared password, no user accounts** (same approach as the
  `60-anni-daniele-gd` project): `ADMIN_PASSWORD` in `.env`, sent by the
  `/admin` page in the `X-Admin-Password` header on every `/api/admin/*`
  request. No server-side sessions or tokens, so nothing to store or expire.
  Compared with `secrets.compare_digest` (no timing leak). The page keeps the
  password in `sessionStorage`, cleared when the browser closes.
- **Fail closed**: with `ADMIN_PASSWORD` unset the admin API answers 503 for
  every request instead of falling back to a default password.
- **HTTPS is required** for the password to travel safely; in production
  Caddy terminates TLS. There is no brute-force throttling: acceptable for a
  personal app with a long random password, mitigable later with Caddy rate
  limiting.
- **Requester IP**: saved as `client_ip` in the story record at creation and
  exposed only by the admin API; `_public_record` strips it from every public
  response. Caddy (no `trusted_proxies` configured) replaces any
  client-supplied `X-Forwarded-For` with the real peer address, so the last
  entry of that header is trusted; without a proxy the socket peer is used.
  Host port 8082 is not reachable from the internet, so the header cannot be
  forged from outside. Stories created before this change have no IP.
  An IP address is personal data: it stays in the record until the story is
  deleted.
- **Deletion** removes the record and every audio file of the story. Stories
  still `generating` are refused with 409: the background narration task
  would otherwise keep writing part files for a deleted record.

## Containerization & deployment

- **Two-stage uv build**: builder stage runs `uv sync --frozen --no-dev` with
  bind-mounted `pyproject.toml`/`uv.lock` and a cache mount, so the deps layer
  is rebuilt only when the lockfile changes; code changes rebuild two COPY
  layers in seconds. `UV_PYTHON_DOWNLOADS=0` pins the image interpreter; the
  runtime base (`python:3.13-slim-bookworm`) is the same image the uv builder
  derives from, so the venv symlinks stay valid.
- **Image built on the target instance** (rsync sources + `docker compose up
  -d --build`) instead of a registry: no registry account/credentials to
  manage for a personal project, and every transitive compiled dependency
  ships aarch64 wheels, so the ARM build needs no compiler and stays fast
  even on 2 OCPUs.
- **Allowlist `.dockerignore`** (`*` then `!app !static !pyproject.toml
  !uv.lock`): `.env`, `data/`, `.git` and tests can never leak into the build
  context or image layers.
- **Named volume for `/data/stories`** rather than a bind mount: the deploy
  rsync uses `--delete`, which would wipe a bind-mounted cache under the app
  dir; a named volume survives deploys, rebuilds and `docker compose down`.
  `STORIES_DIR` is forced in the compose `environment` (wins over `.env`) so
  it always matches the mount point.
- **Non-root container user**; `/data/stories` is pre-created and chowned in
  the image so an empty named volume inherits the right ownership.
- **Healthcheck via a python/urllib one-liner** on `GET /api/config`: the
  slim image has no curl and installing one for healthchecks is not worth it.
- **Single worker / single replica** (no `--workers`, never scale the
  service): fire-and-forget narration tasks and the 429 rate-limit state are
  in-process. `stop_grace_period: 60s` covers draining multi-MB WAV downloads
  on shutdown; interrupted narrations are healed by `cleanup()` at startup.
- **No auth on the public endpoints** (home-use design; only `/api/admin/*`
  is password-protected): public access goes only
  through the Caddy reverse proxy at https://ia-notte.relli.it (HTTPS,
  auto-TLS; host port 8082 is closed in the OCI security list). Accepted
  trade-off — an outsider finding the URL could still consume Gemini quota;
  future mitigation if needed: shared token or basic auth at the proxy.

## Testing

- pytest; all external calls mocked (`httpx.MockTransport` for the Gemini
  client, a fake client object for API tests). Async tests run through the
  anyio pytest plugin already shipped as an httpx/starlette dependency.
