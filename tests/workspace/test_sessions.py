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
        session_id="s_test_001",
        channel="telegram",
        chat_id="c1",
        messages=messages,
    )
    snapshot = repository.read_snapshot("s_test_001")

    assert path.parent == tmp_path / "runtime" / "resume"
    assert snapshot is not None
    assert snapshot.session_id == "s_test_001"
    assert snapshot.channel == "telegram"
    assert snapshot.chat_id == "c1"
    assert snapshot.messages == messages


def test_session_repository_resolves_sessions_dir(tmp_path: Path) -> None:
    repository = SessionRepository(tmp_path)
    repository.write_snapshot(
        session_id="s_test_002",
        channel="telegram",
        chat_id="c2",
        messages=[{"role": "user", "content": "hi"}],
    )

    expected_dir = tmp_path / "runtime" / "resume"
    assert repository.snapshot_path("s_test_002").parent == expected_dir


def test_session_repository_deletes_snapshot_file(tmp_path: Path) -> None:
    repository = SessionRepository(tmp_path)
    repository.write_snapshot(
        session_id="s_test_003",
        channel="telegram",
        chat_id="c3",
        messages=[{"role": "user", "content": "hi"}],
    )

    path = repository.snapshot_path("s_test_003")
    assert path.exists()

    repository.delete_snapshot("s_test_003")

    assert not path.exists()
