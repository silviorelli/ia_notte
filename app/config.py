"""Application configuration read from environment variables (.env supported)."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
STORIES_DIR = Path(os.getenv("STORIES_DIR", str(BASE_DIR / "data" / "stories")))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")


def _model_list(env_var: str, default: str) -> tuple[str, ...]:
    """Parse a comma-separated model list from the environment.

    Args:
        env_var: Name of the environment variable to read.
        default: Fallback value when the variable is unset.

    Returns:
        Ordered tuple of model names to try (first is preferred).
    """
    return tuple(m.strip() for m in os.getenv(env_var, default).split(",") if m.strip())


TEXT_MODELS = _model_list(
    "GEMINI_TEXT_MODEL", "gemini-2.5-flash,gemini-flash-latest,gemini-2.5-flash-lite"
)
TTS_MODELS = _model_list(
    "GEMINI_TTS_MODEL",
    "gemini-3.1-flash-tts-preview,gemini-2.5-flash-preview-tts,gemini-2.5-pro-preview-tts",
)
TTS_VOICE = os.getenv("GEMINI_TTS_VOICE", "Sulafat")
TTS_LANGUAGE = os.getenv("GEMINI_TTS_LANGUAGE", "it-IT")

# Max chars per TTS chunk: first value for chunk 1, second for chunk 2, ...;
# the last value repeats for all remaining chunks. A small first chunk keeps
# time-to-first-audio around 10 seconds.
TTS_CHUNK_PLAN = tuple(int(size) for size in os.getenv("TTS_CHUNK_PLAN", "300,600,1200").split(","))
TTS_CONCURRENCY = int(os.getenv("TTS_CONCURRENCY", "1"))

# I personaggi scritti a mano finiscono dentro i prompt: un limite corto
# riduce lo spazio per iniezioni che tentino di alterare le salvaguardie.
MAX_CUSTOM_CHARACTER_LENGTH = 20

PRESET_CHARACTERS = [
    "Barbie",
    "Minnie",
    "Elsa",
    "Peppa Pig",
    "Bluey",
    "Topolino",
]

DEFAULT_PLAYBACK_RATE = 1.0
RECENT_STORIES_LIMIT = 20
