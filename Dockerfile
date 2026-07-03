# syntax=docker/dockerfile:1

# Builder: install locked dependencies into /app/.venv with uv.
# The project has no build-system, so uv treats it as virtual: a single
# `uv sync` installs dependencies only — no source needed at this stage.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev

# Runtime: same base the uv image derives from, so the venv's interpreter
# symlinks resolve identically.
FROM python:3.13-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    STORIES_DIR=/data/stories
WORKDIR /app
# Pre-create the cache dir so an empty named volume mounted at /data/stories
# inherits app-user ownership on first use.
RUN groupadd -r app && useradd -r -g app app \
    && mkdir -p /data/stories && chown -R app:app /data/stories
COPY --from=builder /app/.venv /app/.venv
COPY app/ ./app/
COPY static/ ./static/
USER app
EXPOSE 8000
# Exec form: uvicorn is PID 1 and receives SIGTERM directly.
# Single worker only: narration tasks and rate-limit state live in-process.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
