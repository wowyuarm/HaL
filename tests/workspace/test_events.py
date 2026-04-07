from __future__ import annotations

from pathlib import Path

import hal.workspace.events as events_module
from hal.workspace.events import EventLogRepository


def test_event_log_repository_appends_and_reads_session_events(tmp_path: Path) -> None:
    repo = EventLogRepository(tmp_path)

    first = repo.append(
        session="s_1",
        event_type="user_message",
        channel="telegram",
        chat_id="chat-1",
        payload={"content": "hello"},
    )
    repo.append(
        session="s_2",
        event_type="user_message",
        channel="telegram",
        chat_id="chat-2",
        payload={"content": "ignore"},
    )
    second = repo.append(
        session="s_1",
        event_type="assistant",
        payload={"content": "hi"},
    )

    assert repo.file_path == tmp_path / "runtime" / "logs" / "events.jsonl"
    assert first.session == "s_1"
    assert second.type == "assistant"

    rows = repo.read_session("s_1")

    assert [row.type for row in rows] == ["user_message", "assistant"]
    assert rows[0].payload == {"content": "hello"}
    assert rows[1].payload == {"content": "hi"}


def test_event_log_repository_reuses_cache_when_file_unchanged(
    tmp_path: Path, monkeypatch
) -> None:
    repo = EventLogRepository(tmp_path)
    repo.append(session="s_1", event_type="user_message", payload={"content": "hello"})

    calls = 0
    original = events_module.read_jsonl_lines

    def counting_read(path: Path) -> list[str]:
        nonlocal calls
        calls += 1
        return original(path)

    monkeypatch.setattr(events_module, "read_jsonl_lines", counting_read)

    first = repo.read_session("s_1")
    second = repo.read_session("s_1")

    assert [row.type for row in first] == ["user_message"]
    assert [row.type for row in second] == ["user_message"]
    assert calls == 1


def test_event_log_repository_refreshes_cache_after_append(tmp_path: Path) -> None:
    repo = EventLogRepository(tmp_path)
    repo.append(session="s_1", event_type="user_message", payload={"content": "hello"})

    first = repo.read_session("s_1")
    repo.append(session="s_1", event_type="assistant", payload={"content": "hi"})
    second = repo.read_session("s_1")

    assert [row.type for row in first] == ["user_message"]
    assert [row.type for row in second] == ["user_message", "assistant"]
