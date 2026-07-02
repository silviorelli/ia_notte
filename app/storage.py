"""Filesystem cache for generated stories and their audio files."""

import json
import logging
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_STORY_ID_PATTERN = re.compile(r"^[0-9a-f]{12}$")


class StoryStore:
    """Stores each story as a JSON record plus a sibling WAV file."""

    def __init__(self, directory: Path) -> None:
        """Create the store, ensuring the target directory exists.

        Args:
            directory: Directory where stories and audio are saved.
        """
        self._directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    def save(self, character: str, story: str, audio_wav: bytes) -> dict:
        """Persist a story and its audio, returning the saved record.

        Args:
            character: Protagonist name used for the story.
            story: Generated story text.
            audio_wav: WAV audio bytes of the narrated story.

        Returns:
            Record dict with ``id``, ``character``, ``story`` and ``created_at``.
        """
        story_id = uuid.uuid4().hex[:12]
        record = {
            "id": story_id,
            "character": character,
            "story": story,
            "created_at": datetime.now(UTC).isoformat(),
        }
        (self._directory / f"{story_id}.wav").write_bytes(audio_wav)
        (self._directory / f"{story_id}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return record

    def get(self, story_id: str) -> dict | None:
        """Load a story record by id.

        Args:
            story_id: Identifier returned by :meth:`save`.

        Returns:
            The record dict, or ``None`` if the id is invalid or unknown.
        """
        if not _STORY_ID_PATTERN.match(story_id):
            return None
        path = self._directory / f"{story_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def audio_path(self, story_id: str) -> Path | None:
        """Return the WAV file path for a story, if it exists.

        Args:
            story_id: Identifier returned by :meth:`save`.

        Returns:
            Path to the WAV file, or ``None`` if invalid or missing.
        """
        if not _STORY_ID_PATTERN.match(story_id):
            return None
        path = self._directory / f"{story_id}.wav"
        return path if path.exists() else None

    def list_recent(self, limit: int) -> list[dict]:
        """List the most recent stories, newest first.

        Args:
            limit: Maximum number of records to return.

        Returns:
            List of records with ``id``, ``character`` and ``created_at`` only.
        """
        records = []
        for path in self._directory.glob("*.json"):
            try:
                records.append(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError) as exc:
                logger.error("Skipping unreadable story file %s: %s", path.name, exc)
        records.sort(key=lambda record: record.get("created_at", ""), reverse=True)
        return [
            {key: record.get(key) for key in ("id", "character", "created_at")}
            for record in records[:limit]
        ]
