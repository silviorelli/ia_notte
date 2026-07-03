# Commands Cheatsheet

## Setup

```bash
cp .env.example .env        # then set GEMINI_API_KEY inside .env
uv sync --all-groups        # optional: uv run does this on demand
```

## Run

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000            # serve the app
uv run uvicorn app.main:app --reload                              # dev mode, auto-reload
```

App: http://localhost:8000 (from a phone: http://<computer-ip>:8000)
Interactive API docs (FastAPI): http://localhost:8000/docs

## Docker

```bash
docker compose up -d --build     # build the image and start on :8082
docker compose logs -f           # follow app logs
docker compose ps                # status + health
docker compose down              # stop (add -v to ALSO delete the story cache)
docker volume inspect ia_notte_stories   # where the cache volume lives
```

Production deploy (OCI instance) lives in the infra repo:
`infra_relli/scripts/deploy-ia-notte.sh`.

## Quality

```bash
uv run pytest               # full test suite (Gemini calls are mocked)
uv run pytest -q tests/test_gemini.py    # one file
uv run ruff check .         # lint
uv run ruff format .        # format
```

## Documentation

```bash
# Regenerate the OpenAPI contract after changing endpoints
uv run python -c "import json; from app.main import app; \
print(json.dumps(app.openapi(), indent=2, ensure_ascii=False))" > documentation/api.json
```

## Maintenance

```bash
rm -rf data/stories         # clear the story/audio cache (regenerated on demand)
```
