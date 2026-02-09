from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from hal.session.manager import Session, SessionManager


def test_get_or_create_caches_session(tmp_home: Path) -> None:
    mgr = SessionManager(workspace=tmp_home)
    s1 = mgr.get_or_create("cli:direct")
    s2 = mgr.get_or_create("cli:direct")
    assert s1 is s2


def test_save_and_load_roundtrip(tmp_home: Path) -> None:
    mgr = SessionManager(workspace=tmp_home)

    session = mgr.get_or_create("telegram:123")
    session.add_message("user", "hi")
    session.add_message("assistant", "hello")
    mgr.save(session)

    # Recreate manager → should load from disk
    mgr2 = SessionManager(workspace=tmp_home)
    loaded = mgr2.get_or_create("telegram:123")

    assert loaded.key == "telegram:123"
    assert loaded.get_history() == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


def test_delete_removes_session_file(tmp_home: Path) -> None:
    mgr = SessionManager(workspace=tmp_home)
    session = mgr.get_or_create("cli:direct")
    session.add_message("user", "x")
    mgr.save(session)

    assert mgr.delete("cli:direct") is True
    assert mgr.delete("cli:direct") is False


def test_list_sessions_reads_metadata_and_sorts(tmp_home: Path) -> None:
    mgr = SessionManager(workspace=tmp_home)

    s1 = Session(key="cli:one")
    s1.created_at = datetime(2020, 1, 1, 0, 0, 0)
    s1.updated_at = datetime(2020, 1, 1, 0, 0, 1)
    mgr.save(s1)

    s2 = Session(key="cli:two")
    s2.created_at = datetime(2020, 1, 1, 0, 0, 0)
    s2.updated_at = datetime(2020, 1, 2, 0, 0, 0)
    mgr.save(s2)

    sessions = mgr.list_sessions()
    assert [s["key"] for s in sessions[:2]] == ["cli:two", "cli:one"]
    assert sessions[0]["path"].endswith(".jsonl")


def test_load_handles_corrupt_json_and_returns_none(tmp_home: Path) -> None:
    mgr = SessionManager(workspace=tmp_home)

    path = mgr._get_session_path("cli:broken")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json}\n", encoding="utf-8")

    loaded = mgr._load("cli:broken")
    assert loaded is None

    # get_or_create should fall back to a new empty session
    s = mgr.get_or_create("cli:broken")
    assert s.messages == []


def test_session_save_format_includes_metadata_line(tmp_home: Path) -> None:
    mgr = SessionManager(workspace=tmp_home)

    s = Session(key="cli:meta")
    s.metadata["x"] = 1
    s.add_message("user", "hi")
    mgr.save(s)

    raw = mgr._get_session_path("cli:meta").read_text(encoding="utf-8").splitlines()
    first = json.loads(raw[0])
    assert first.get("_type") == "metadata"
    assert first.get("metadata") == {"x": 1}

    msg = json.loads(raw[1])
    assert msg["role"] == "user"
    assert msg["content"] == "hi" 
