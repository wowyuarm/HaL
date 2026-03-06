from __future__ import annotations

from pathlib import Path

from hal.workspace.sessions import SessionRepository


def test_session_repository_writes_and_reads_snapshot(tmp_path: Path) -> None:
    repository = SessionRepository(tmp_path)
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
    ]

    path = repository.write_snapshot(
        session_key="telegram:c1",
        channel="telegram",
        chat_id="c1",
        messages=messages,
    )
    snapshot = repository.read_snapshot("telegram:c1")

    assert path.parent == tmp_path / "logs" / "sessions"
    assert snapshot is not None
    assert snapshot.session_key == "telegram:c1"
    assert snapshot.channel == "telegram"
    assert snapshot.chat_id == "c1"
    assert snapshot.messages == messages


def test_session_repository_prefers_v3_sessions_dir(tmp_path: Path) -> None:
    (tmp_path / "runtime" / "sessions").mkdir(parents=True)
    repository = SessionRepository(tmp_path)
    repository.write_snapshot(
        session_key="telegram:c2",
        channel="telegram",
        chat_id="c2",
        messages=[{"role": "user", "content": "hi"}],
    )

    expected_dir = tmp_path / "runtime" / "sessions"
    assert repository.snapshot_path("telegram:c2").parent == expected_dir


def test_session_repository_deletes_snapshot_file(tmp_path: Path) -> None:
    repository = SessionRepository(tmp_path)
    repository.write_snapshot(
        session_key="telegram:c3",
        channel="telegram",
        chat_id="c3",
        messages=[{"role": "user", "content": "hi"}],
    )

    path = repository.snapshot_path("telegram:c3")
    assert path.exists()

    repository.delete_snapshot("telegram:c3")

    assert not path.exists()
