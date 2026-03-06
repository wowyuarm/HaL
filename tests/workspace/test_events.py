from __future__ import annotations

from pathlib import Path

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

    assert repo.file_path == tmp_path / "logs" / "events.jsonl"
    assert first.session == "s_1"
    assert second.type == "assistant"

    rows = repo.read_session("s_1")

    assert [row.type for row in rows] == ["user_message", "assistant"]
    assert rows[0].payload == {"content": "hello"}
    assert rows[1].payload == {"content": "hi"}
