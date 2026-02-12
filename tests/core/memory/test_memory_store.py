from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from hal.core.memory.store import MemoryStore


def test_read_today_empty_when_missing(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    assert store.read_today() == ""


def test_append_today_creates_file_with_header(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Freeze date
    monkeypatch.setattr("hal.core.memory.store.today_date", lambda: "2020-01-01")

    store = MemoryStore(tmp_path)
    store.append_today("hello")

    f = store.memory_dir / "2020-01-01.md"
    text = f.read_text(encoding="utf-8")
    assert text.startswith("# 2020-01-01")
    assert "hello" in text


def test_append_today_appends_when_file_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("hal.core.memory.store.today_date", lambda: "2020-01-01")

    store = MemoryStore(tmp_path)
    store.append_today("first")
    store.append_today("second")

    f = store.memory_dir / "2020-01-01.md"
    text = f.read_text(encoding="utf-8")
    assert "first" in text
    assert "second" in text


def test_long_term_read_write_and_context(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    assert store.read_long_term() == ""

    store.write_long_term("LT")
    assert store.read_long_term() == "LT"

    # With no today notes
    ctx = store.get_memory_context()
    assert "Long-term Memory" in ctx
    assert "LT" in ctx


def test_get_recent_memories_and_list_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = MemoryStore(tmp_path)

    # Create two daily files
    (store.memory_dir / "2020-01-01.md").write_text("d1", encoding="utf-8")
    (store.memory_dir / "2020-01-02.md").write_text("d2", encoding="utf-8")

    # Freeze today to 2020-01-02
    class _D(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2020, 1, 2)

    monkeypatch.setattr("hal.core.memory.store.datetime", _D)

    recent = store.get_recent_memories(days=3)
    assert "d2" in recent
    assert "d1" in recent
    assert "---" in recent

    files = store.list_memory_files()
    assert [p.name for p in files] == ["2020-01-02.md", "2020-01-01.md"]


def test_memory_context_includes_today_section(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("hal.core.memory.store.today_date", lambda: "2020-01-01")

    store = MemoryStore(tmp_path)
    store.append_today("note")

    ctx = store.get_memory_context()
    assert "Today's Notes" in ctx
    assert "note" in ctx
