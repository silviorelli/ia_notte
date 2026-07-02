"""Filesystem cache for generated stories, their audio and narration progress.

Each story is a JSON record plus audio files. While narration is in
progress the record has ``status: "generating"`` and one ``{id}.part{n}.wav``
file per completed chunk; on completion the parts are concatenated into
``{id}.wav`` and the status becomes ``"ready"``.
"""

import json
import logging
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_STORY_ID_PATTERN = re.compile(r"^[0-9a-f]{12}$")

STATUS_GENERATING = "generating"
STATUS_READY = "ready"
STATUS_ERROR = "error"


class StoryStore:
    """Stores each story as a JSON record plus sibling WAV files."""

    def __init__(self, directory: Path) -> None:
        """Create the store, ensuring the target directory exists.

        Args:
            directory: Directory where stories and audio are saved.
        """
        self._directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    def save(self, character: str, story: str, chunks_total: int) -> dict:
        """Persist a new story record with narration still in progress.

        Args:
            character: Protagonist name used for the story.
            story: Generated story text.
            chunks_total: Number of audio chunks that will be synthesized.

        Returns:
            Record dict with ``status`` set to ``"generating"``.
        """
        record = {
            "id": uuid.uuid4().hex[:12],
            "character": character,
            "story": story,
            "created_at": datetime.now(UTC).isoformat(),
            "status": STATUS_GENERATING,
            "chunks_total": chunks_total,
            "chunks_ready": 0,
        }
        self._write_record(record)
        return record

    def save_part(self, story_id: str, index: int, audio_wav: bytes) -> None:
        """Write the WAV file for one narration chunk.

        Args:
            story_id: Identifier returned by :meth:`save`.
            index: Zero-based chunk index.
            audio_wav: WAV audio bytes of the chunk.
        """
        (self._directory / f"{story_id}.part{index}.wav").write_bytes(audio_wav)

    def set_progress(self, story_id: str, chunks_ready: int) -> None:
        """Update how many chunks (contiguous from the start) are playable.

        Args:
            story_id: Identifier returned by :meth:`save`.
            chunks_ready: Count of ready chunks starting from index 0.
        """
        record = self.get(story_id)
        if record is None:
            return
        record["chunks_ready"] = chunks_ready
        self._write_record(record)

    def finalize(self, story_id: str, audio_wav: bytes) -> None:
        """Store the complete narration and mark the story ready.

        Part files are kept on disk so a client that is still playing them
        does not break; they are removed by :meth:`cleanup` at next startup.

        Args:
            story_id: Identifier returned by :meth:`save`.
            audio_wav: WAV audio bytes of the full narration.
        """
        record = self.get(story_id)
        if record is None:
            return
        (self._directory / f"{story_id}.wav").write_bytes(audio_wav)
        record["status"] = STATUS_READY
        record["chunks_ready"] = record.get("chunks_total", 0)
        self._write_record(record)

    def mark_error(self, story_id: str) -> None:
        """Mark a story whose narration failed.

        Args:
            story_id: Identifier returned by :meth:`save`.
        """
        record = self.get(story_id)
        if record is None:
            return
        record["status"] = STATUS_ERROR
        self._write_record(record)

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
        return _normalize(json.loads(path.read_text(encoding="utf-8")))

    def audio_path(self, story_id: str) -> Path | None:
        """Return the full-narration WAV path for a story, if it exists.

        Args:
            story_id: Identifier returned by :meth:`save`.

        Returns:
            Path to the WAV file, or ``None`` if invalid or missing.
        """
        if not _STORY_ID_PATTERN.match(story_id):
            return None
        path = self._directory / f"{story_id}.wav"
        return path if path.exists() else None

    def part_path(self, story_id: str, index: int) -> Path | None:
        """Return the WAV path of one narration chunk, if it exists.

        Args:
            story_id: Identifier returned by :meth:`save`.
            index: Zero-based chunk index.

        Returns:
            Path to the part file, or ``None`` if invalid or missing.
        """
        if not _STORY_ID_PATTERN.match(story_id) or not 0 <= index < 1000:
            return None
        path = self._directory / f"{story_id}.part{index}.wav"
        return path if path.exists() else None

    def list_recent(self, limit: int) -> list[dict]:
        """List the most recent stories, newest first.

        Args:
            limit: Maximum number of records to return.

        Returns:
            List of records with ``id``, ``character``, ``created_at``
            and ``status`` only.
        """
        records = []
        for path in self._directory.glob("*.json"):
            try:
                records.append(_normalize(json.loads(path.read_text(encoding="utf-8"))))
            except (json.JSONDecodeError, OSError) as exc:
                logger.error("Skipping unreadable story file %s: %s", path.name, exc)
        records.sort(key=lambda record: record.get("created_at", ""), reverse=True)
        return [
            {key: record.get(key) for key in ("id", "character", "created_at", "status")}
            for record in records[:limit]
        ]

    def cleanup(self) -> None:
        """Recover state at startup.

        Stories stuck in ``generating`` (their background task died with the
        previous process) are marked as errors, and leftover part files of
        completed stories are deleted.
        """
        for path in self._directory.glob("*.json"):
            record = self.get(path.stem)
            if record is None:
                continue
            if record["status"] == STATUS_GENERATING:
                logger.error("Story %s was interrupted by a restart, marking error", record["id"])
                self.mark_error(record["id"])
            elif record["status"] == STATUS_READY:
                for part in self._directory.glob(f"{record['id']}.part*.wav"):
                    part.unlink()

    def _write_record(self, record: dict) -> None:
        """Atomically write a record so readers never see partial JSON."""
        path = self._directory / f"{record['id']}.json"
        temp_path = path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(path)


def _normalize(record: dict) -> dict:
    """Fill status fields missing from records created before chunked audio."""
    record.setdefault("status", STATUS_READY)
    record.setdefault("chunks_total", 1)
    record.setdefault("chunks_ready", record["chunks_total"])
    return record
