"""Tests for the filesystem story cache."""

from pathlib import Path

from app.storage import StoryStore


def test_save_and_get_roundtrip(tmp_path: Path):
    store = StoryStore(tmp_path)
    record = store.save("Elsa", "C'era una volta Elsa.", b"RIFFfake")
    loaded = store.get(record["id"])
    assert loaded == record
    assert store.audio_path(record["id"]).read_bytes() == b"RIFFfake"


def test_get_unknown_or_invalid_id_returns_none(tmp_path: Path):
    store = StoryStore(tmp_path)
    assert store.get("aaaaaaaaaaaa") is None
    assert store.get("../../etc/passwd") is None
    assert store.audio_path("../escape") is None


def test_list_recent_sorted_and_limited(tmp_path: Path):
    store = StoryStore(tmp_path)
    ids = [store.save(f"Char{i}", f"Storia {i}", b"x")["id"] for i in range(5)]
    recent = store.list_recent(limit=3)
    assert len(recent) == 3
    assert [r["id"] for r in recent] == list(reversed(ids))[:3]
    assert all(set(r) == {"id", "character", "created_at"} for r in recent)


def test_list_recent_skips_corrupted_files(tmp_path: Path):
    store = StoryStore(tmp_path)
    store.save("Minnie", "Storia valida.", b"x")
    (tmp_path / "aaaaaaaaaaab.json").write_text("{ not json", encoding="utf-8")
    recent = store.list_recent(limit=10)
    assert len(recent) == 1
    assert recent[0]["character"] == "Minnie"
