"""Tests for SessionStore and ThreadRefsRepository."""

from __future__ import annotations

from pathlib import Path

import pytest

from hal.domain.events import SESSION_CREATED, TURN_STARTED, SessionEvent
from hal.domain.session import SessionManifest
from hal.workspace.layout import WorkspaceLayout
from hal.workspace.session_store import SessionStore
from hal.workspace.thread_refs import ThreadRefsRepository, ThreadSessionRef


# ---------------------------------------------------------------------------
# SessionStore
# ---------------------------------------------------------------------------


class TestSessionStore:
    @pytest.fixture
    def store(self, tmp_path: Path) -> SessionStore:
        return SessionStore(WorkspaceLayout(tmp_path))

    def test_create_and_read_manifest(self, store: SessionStore) -> None:
        manifest = SessionManifest(
            session_id="s_test_001",
            primary_thread="auth",
            mounted_threads=["auth", "memory"],
        )
        store.create("s_test_001")
        store.write_manifest("s_test_001", manifest)

        loaded = store.read_manifest("s_test_001")
        assert loaded is not None
        assert loaded.session_id == "s_test_001"
        assert loaded.primary_thread == "auth"
        assert loaded.mounted_threads == ["auth", "memory"]

    def test_read_manifest_missing(self, store: SessionStore) -> None:
        assert store.read_manifest("nonexistent") is None

    def test_append_and_read_events(self, store: SessionStore) -> None:
        sid = "s_test_002"
        store.create(sid)

        e1 = SessionEvent(seq=1, session_id=sid, type=SESSION_CREATED, actor="engine")
        e2 = SessionEvent(
            seq=2, session_id=sid, type=TURN_STARTED, actor="engine", turn_id="t_0001"
        )
        store.append_event(sid, e1)
        store.append_event(sid, e2)

        events = store.read_events(sid)
        assert len(events) == 2
        assert events[0].seq == 1
        assert events[1].seq == 2

    def test_read_events_after_seq(self, store: SessionStore) -> None:
        sid = "s_test_003"
        store.create(sid)

        for i in range(1, 6):
            store.append_event(
                sid,
                SessionEvent(seq=i, session_id=sid, type=TURN_STARTED, actor="engine"),
            )

        events = store.read_events(sid, after_seq=3)
        assert len(events) == 2
        assert events[0].seq == 4
        assert events[1].seq == 5

    def test_read_events_empty(self, store: SessionStore) -> None:
        assert store.read_events("nonexistent") == []

    def test_list_sessions_empty(self, store: SessionStore) -> None:
        assert store.list_sessions() == []

    def test_list_sessions_all(self, store: SessionStore) -> None:
        for i in range(3):
            sid = f"s_test_{i:03d}"
            store.create(sid)
            store.write_manifest(sid, SessionManifest(session_id=sid))

        results = store.list_sessions()
        assert len(results) == 3

    def test_list_sessions_filter_status(self, store: SessionStore) -> None:
        store.create("s_active")
        store.write_manifest("s_active", SessionManifest(session_id="s_active", status="active"))
        store.create("s_ended")
        store.write_manifest("s_ended", SessionManifest(session_id="s_ended", status="ended"))

        active = store.list_sessions(status="active")
        assert len(active) == 1
        assert active[0].session_id == "s_active"

    def test_list_sessions_filter_thread(self, store: SessionStore) -> None:
        store.create("s_auth")
        store.write_manifest(
            "s_auth",
            SessionManifest(session_id="s_auth", primary_thread="auth"),
        )
        store.create("s_other")
        store.write_manifest(
            "s_other",
            SessionManifest(session_id="s_other", primary_thread="web"),
        )

        results = store.list_sessions(thread_slug="auth")
        assert len(results) == 1
        assert results[0].session_id == "s_auth"

    def test_list_sessions_excludes_archived_by_default(self, store: SessionStore) -> None:
        store.create("s_ended")
        store.write_manifest(
            "s_ended",
            SessionManifest(session_id="s_ended", status="ended", archived_at="2026-03-26T15:00:00"),
        )

        assert store.list_sessions() == []
        included = store.list_sessions(include_archived=True)
        assert len(included) == 1
        assert included[0].session_id == "s_ended"

    def test_archive_and_restore_terminal_session(self, store: SessionStore) -> None:
        store.create("s_done")
        store.write_manifest("s_done", SessionManifest(session_id="s_done", status="ended"))

        archived = store.archive("s_done")
        assert archived is not None
        assert archived.archived_at is not None

        restored = store.restore("s_done")
        assert restored is not None
        assert restored.archived_at is None

    def test_archive_rejects_non_terminal_session(self, store: SessionStore) -> None:
        store.create("s_live")
        store.write_manifest("s_live", SessionManifest(session_id="s_live", status="active"))

        with pytest.raises(ValueError, match="not archivable"):
            store.archive("s_live")

    def test_list_sessions_ignores_touched_threads_for_thread_membership(
        self, store: SessionStore
    ) -> None:
        store.create("s_auth")
        store.write_manifest(
            "s_auth",
            SessionManifest(
                session_id="s_auth",
                primary_thread="auth",
                mounted_threads=["auth"],
                touched_threads=["memory"],
            ),
        )

        assert store.list_sessions(thread_slug="memory") == []

    def test_delete(self, store: SessionStore) -> None:
        sid = "s_delete_me"
        store.create(sid)
        store.write_manifest(sid, SessionManifest(session_id=sid))
        assert store.read_manifest(sid) is not None

        store.delete(sid)
        assert store.read_manifest(sid) is None
        assert not store.session_dir(sid).exists()

    def test_delete_nonexistent(self, store: SessionStore) -> None:
        store.delete("ghost")  # should not raise

    def test_write_manifest_id_mismatch_raises(self, store: SessionStore) -> None:
        manifest = SessionManifest(session_id="s_wrong")
        store.create("s_correct")
        with pytest.raises(ValueError, match="manifest session_id"):
            store.write_manifest("s_correct", manifest)


# ---------------------------------------------------------------------------
# ThreadRefsRepository
# ---------------------------------------------------------------------------


class TestThreadRefsRepository:
    @pytest.fixture
    def repo(self, tmp_path: Path) -> ThreadRefsRepository:
        return ThreadRefsRepository(WorkspaceLayout(tmp_path))

    def test_append_and_read(self, repo: ThreadRefsRepository, tmp_path: Path) -> None:
        # create thread dir so refs can be written
        (tmp_path / "work" / "threads" / "auth" / "refs").mkdir(parents=True, exist_ok=True)

        ref1 = ThreadSessionRef(session_id="s_001", role="primary")
        ref2 = ThreadSessionRef(session_id="s_002", role="mounted")
        repo.append_ref("auth", ref1)
        repo.append_ref("auth", ref2)

        refs = repo.read_refs("auth")
        assert len(refs) == 2
        assert refs[0].session_id == "s_001"
        assert refs[0].role == "primary"
        assert refs[1].role == "mounted"

    def test_read_empty(self, repo: ThreadRefsRepository) -> None:
        assert repo.read_refs("nonexistent") == []
