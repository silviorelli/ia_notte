"""Tests for the filesystem story cache and narration lifecycle."""

import json
from pathlib import Path

from app.storage import STATUS_ERROR, STATUS_GENERATING, STATUS_READY, StoryStore


def test_save_starts_generating_and_finalize_completes(tmp_path: Path):
    store = StoryStore(tmp_path)
    record = store.save("Elsa", "C'era una volta Elsa.", chunks_total=2)
    assert record["status"] == STATUS_GENERATING
    assert record["chunks_ready"] == 0
    assert record["parts_done"] == []
    assert store.audio_path(record["id"]) is None

    store.save_part(record["id"], 1, b"RIFFpart1")
    store.set_progress(record["id"], 0, [1])
    loaded = store.get(record["id"])
    assert loaded["chunks_ready"] == 0
    assert loaded["parts_done"] == [1]
    assert store.part_path(record["id"], 1).read_bytes() == b"RIFFpart1"
    assert store.part_path(record["id"], 0) is None

    store.finalize(record["id"], b"RIFFfull", [0.0, 12.5])
    loaded = store.get(record["id"])
    assert loaded["status"] == STATUS_READY
    assert loaded["chunks_ready"] == 2
    assert loaded["parts_done"] == [0, 1]
    assert loaded["chapter_offsets"] == [0.0, 12.5]
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
    assert record["parts_done"] == [0]
    assert "chapter_offsets" not in record


def test_cleanup_marks_stale_and_removes_leftover_parts(tmp_path: Path):
    store = StoryStore(tmp_path)
    stale = store.save("Bluey", "Storia interrotta.", chunks_total=2)
    store.save_part(stale["id"], 0, b"RIFFstalepart")
    done = store.save("Elsa", "Storia completa.", chunks_total=1)
    store.save_part(done["id"], 0, b"RIFFpart")
    store.finalize(done["id"], b"RIFFfull", [0.0])

    store.cleanup()

    assert store.get(stale["id"])["status"] == STATUS_ERROR
    assert store.part_path(stale["id"], 0) is None
    assert store.part_path(done["id"], 0) is None
    assert store.audio_path(done["id"]) is not None


def test_list_recent_sorted_paginated_with_status(tmp_path: Path):
    store = StoryStore(tmp_path)
    ids = [store.save(f"Char{i}", f"Storia {i}", chunks_total=1)["id"] for i in range(5)]
    newest_first = list(reversed(ids))

    first, total = store.list_recent(page=1, page_size=3)
    second, _ = store.list_recent(page=2, page_size=3)
    beyond, _ = store.list_recent(page=3, page_size=3)

    assert total == 5
    assert [r["id"] for r in first] == newest_first[:3]
    assert [r["id"] for r in second] == newest_first[3:]
    assert beyond == []
    assert all(set(r) == {"id", "character", "created_at", "status"} for r in first)


def test_list_recent_skips_corrupted_files(tmp_path: Path):
    store = StoryStore(tmp_path)
    store.save("Minnie", "Storia valida.", chunks_total=1)
    (tmp_path / "aaaaaaaaaaab.json").write_text("{ not json", encoding="utf-8")
    recent, total = store.list_recent(page=1, page_size=10)
    assert total == 1
    assert len(recent) == 1
    assert recent[0]["character"] == "Minnie"


def test_list_all_includes_client_ip(tmp_path: Path):
    store = StoryStore(tmp_path)
    old = store.save("Elsa", "Storia.", chunks_total=1)
    new = store.save("Bluey", "Storia.", chunks_total=1, client_ip="203.0.113.7")

    listing = store.list_all()

    assert [r["id"] for r in listing] == [new["id"], old["id"]]
    assert listing[0]["client_ip"] == "203.0.113.7"
    assert listing[1]["client_ip"] is None
    assert all(set(r) == {"id", "character", "created_at", "status", "client_ip"} for r in listing)


def test_delete_removes_record_and_all_audio_files(tmp_path: Path):
    store = StoryStore(tmp_path)
    keep = store.save("Bluey", "Storia.", chunks_total=1)
    record = store.save("Elsa", "Storia.", chunks_total=2)
    store.save_part(record["id"], 0, b"RIFFpart0")
    store.finalize(record["id"], b"RIFFfull", [0.0, 1.0])

    assert store.delete(record["id"]) is True

    assert sorted(path.name for path in tmp_path.iterdir()) == [f"{keep['id']}.json"]
    assert store.delete(record["id"]) is False
    assert store.delete("../escape") is False
