"""Tests for the filesystem story cache and narration lifecycle."""

import json
from pathlib import Path

from app.storage import STATUS_ERROR, STATUS_GENERATING, STATUS_READY, StoryStore


def test_save_starts_generating_and_finalize_completes(tmp_path: Path):
    store = StoryStore(tmp_path)
    record = store.save("Elsa", "C'era una volta Elsa.", chunks_total=2)
    assert record["status"] == STATUS_GENERATING
    assert record["chunks_ready"] == 0
    assert store.audio_path(record["id"]) is None

    store.save_part(record["id"], 0, b"RIFFpart0")
    store.set_progress(record["id"], 1)
    assert store.get(record["id"])["chunks_ready"] == 1
    assert store.part_path(record["id"], 0).read_bytes() == b"RIFFpart0"
    assert store.part_path(record["id"], 1) is None

    store.finalize(record["id"], b"RIFFfull")
    loaded = store.get(record["id"])
    assert loaded["status"] == STATUS_READY
    assert loaded["chunks_ready"] == 2
    assert store.audio_path(record["id"]).read_bytes() == b"RIFFfull"


def test_mark_error(tmp_path: Path):
    store = StoryStore(tmp_path)
    record = store.save("Minnie", "Storia.", chunks_total=3)
    store.mark_error(record["id"])
    assert store.get(record["id"])["status"] == STATUS_ERROR


def test_get_unknown_or_invalid_id_returns_none(tmp_path: Path):
    store = StoryStore(tmp_path)
    assert store.get("aaaaaaaaaaaa") is None
    assert store.get("../../etc/passwd") is None
    assert store.audio_path("../escape") is None
    assert store.part_path("../escape", 0) is None
    assert store.part_path("aaaaaaaaaaaa", -1) is None


def test_legacy_record_is_normalized_as_ready(tmp_path: Path):
    store = StoryStore(tmp_path)
    legacy = {
        "id": "aaaaaaaaaaaa",
        "character": "Barbie",
        "story": "Storia vecchia.",
        "created_at": "2026-07-01T00:00:00+00:00",
    }
    (tmp_path / "aaaaaaaaaaaa.json").write_text(json.dumps(legacy), encoding="utf-8")
    record = store.get("aaaaaaaaaaaa")
    assert record["status"] == STATUS_READY
    assert record["chunks_total"] == 1
    assert record["chunks_ready"] == 1


def test_cleanup_marks_stale_and_removes_leftover_parts(tmp_path: Path):
    store = StoryStore(tmp_path)
    stale = store.save("Bluey", "Storia interrotta.", chunks_total=2)
    done = store.save("Elsa", "Storia completa.", chunks_total=1)
    store.save_part(done["id"], 0, b"RIFFpart")
    store.finalize(done["id"], b"RIFFfull")

    store.cleanup()

    assert store.get(stale["id"])["status"] == STATUS_ERROR
    assert store.part_path(done["id"], 0) is None
    assert store.audio_path(done["id"]) is not None


def test_list_recent_sorted_limited_with_status(tmp_path: Path):
    store = StoryStore(tmp_path)
    ids = [store.save(f"Char{i}", f"Storia {i}", chunks_total=1)["id"] for i in range(5)]
    recent = store.list_recent(limit=3)
    assert len(recent) == 3
    assert [r["id"] for r in recent] == list(reversed(ids))[:3]
    assert all(set(r) == {"id", "character", "created_at", "status"} for r in recent)


def test_list_recent_skips_corrupted_files(tmp_path: Path):
    store = StoryStore(tmp_path)
    store.save("Minnie", "Storia valida.", chunks_total=1)
    (tmp_path / "aaaaaaaaaaab.json").write_text("{ not json", encoding="utf-8")
    recent = store.list_recent(limit=10)
    assert len(recent) == 1
    assert recent[0]["character"] == "Minnie"
