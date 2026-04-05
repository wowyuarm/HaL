"""Tests for ThreadSlugMigrator."""

from __future__ import annotations

from pathlib import Path

import pytest

from hal.domain.session import SessionManifest
from hal.workspace.layout import WorkspaceLayout
from hal.workspace.session_store import SessionStore
from hal.workspace.thread_migrator import (
    MigrationConflict,
    MigrationError,
    ThreadSlugMigrator,
    _manifest_references_thread,
    _replace_slug_in_manifest,
)


class TestManifestHelpers:
    def test_references_primary(self) -> None:
        m = SessionManifest(session_id="s_1", primary_thread="alpha")
        assert _manifest_references_thread(m, "alpha")
        assert not _manifest_references_thread(m, "beta")

    def test_references_mounted(self) -> None:
        m = SessionManifest(session_id="s_1", mounted_threads=["alpha", "beta"])
        assert _manifest_references_thread(m, "alpha")
        assert not _manifest_references_thread(m, "gamma")

    def test_references_touched(self) -> None:
        m = SessionManifest(session_id="s_1", touched_threads=["alpha"])
        assert _manifest_references_thread(m, "alpha")

    def test_replace_primary(self) -> None:
        m = SessionManifest(session_id="s_1", primary_thread="old")
        updated = _replace_slug_in_manifest(m, "old", "new")
        assert updated.primary_thread == "new"
        assert m.primary_thread == "old"

    def test_replace_mounted(self) -> None:
        m = SessionManifest(
            session_id="s_1", mounted_threads=["old", "other"], touched_threads=["old"]
        )
        updated = _replace_slug_in_manifest(m, "old", "new")
        assert updated.mounted_threads == ["new", "other"]
        assert updated.touched_threads == ["new"]

    def test_replace_no_match(self) -> None:
        m = SessionManifest(session_id="s_1", primary_thread="alpha")
        updated = _replace_slug_in_manifest(m, "beta", "gamma")
        assert updated.primary_thread == "alpha"


class TestThreadSlugMigrator:
    @pytest.fixture
    def layout(self, tmp_path: Path) -> WorkspaceLayout:
        return WorkspaceLayout(tmp_path)

    @pytest.fixture
    def store(self, layout: WorkspaceLayout) -> SessionStore:
        return SessionStore(layout)

    @pytest.fixture
    def migrator(self, layout: WorkspaceLayout) -> ThreadSlugMigrator:
        return ThreadSlugMigrator(layout)

    def _setup_thread(self, layout: WorkspaceLayout, slug: str) -> None:
        thread_dir = layout.threads_dir() / slug
        thread_dir.mkdir(parents=True)
        (thread_dir / "BRIEF.md").write_text("brief content")
        refs = thread_dir / "refs"
        refs.mkdir()
        (refs / "sessions.jsonl").write_text("")

    def _setup_session(
        self, store: SessionStore, session_id: str, primary: str | None = None,
        mounted: list[str] | None = None, touched: list[str] | None = None,
        status: str = "active",
    ) -> SessionManifest:
        manifest = SessionManifest(
            session_id=session_id,
            primary_thread=primary,
            mounted_threads=mounted or [],
            touched_threads=touched or [],
            status=status,
        )
        store.create(session_id)
        store.write_manifest(session_id, manifest)
        return manifest

    def test_migrate_success(self, migrator: ThreadSlugMigrator,
                             layout: WorkspaceLayout, store: SessionStore) -> None:
        self._setup_thread(layout, "old-slug")
        sid = "s_test_001"
        self._setup_session(store, sid, primary="old-slug",
                            mounted=["old-slug", "other"], status="ended")

        migrator.migrate("old-slug", "new-slug")

        assert (layout.threads_dir() / "new-slug").is_dir()
        assert not (layout.threads_dir() / "old-slug").exists()
        assert (layout.threads_dir() / "new-slug" / "BRIEF.md").exists()
        assert (layout.threads_dir() / "new-slug" / "refs" / "sessions.jsonl").exists()

        updated = store.read_manifest(sid)
        assert updated is not None
        assert updated.primary_thread == "new-slug"
        assert updated.mounted_threads == ["new-slug", "other"]

    def test_migrate_rejects_active_conflict(
        self, migrator: ThreadSlugMigrator, layout: WorkspaceLayout,
        store: SessionStore,
    ) -> None:
        self._setup_thread(layout, "old-slug")
        self._setup_session(store, "s_active", primary="old-slug", status="active")

        with pytest.raises(MigrationConflict):
            migrator.migrate("old-slug", "new-slug")

        # Thread dir should not have been moved
        assert (layout.threads_dir() / "old-slug").is_dir()

    def test_migrate_rejects_identical_slugs(
        self, migrator: ThreadSlugMigrator, layout: WorkspaceLayout,
    ) -> None:
        self._setup_thread(layout, "same-slug")
        with pytest.raises(MigrationError, match="must differ"):
            migrator.migrate("same-slug", "same-slug")

    def test_migrate_rejects_missing_source(
        self, migrator: ThreadSlugMigrator,
    ) -> None:
        with pytest.raises(MigrationError, match="does not exist"):
            migrator.migrate("nonexistent", "new-slug")

    def test_migrate_rejects_existing_target(
        self, migrator: ThreadSlugMigrator, layout: WorkspaceLayout,
    ) -> None:
        self._setup_thread(layout, "old-slug")
        self._setup_thread(layout, "new-slug")
        with pytest.raises(MigrationError, match="already exists"):
            migrator.migrate("old-slug", "new-slug")

    def test_migrate_rollback_on_failure(
        self, migrator: ThreadSlugMigrator, layout: WorkspaceLayout,
        store: SessionStore, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self._setup_thread(layout, "old-slug")
        sid = "s_rollback_001"
        self._setup_session(store, sid, primary="old-slug", status="ended")

        # Sabotage the post-migration step: make refs dir disappear after move
        original_verify = migrator._verify_refs

        def broken_verify(_slug: str) -> None:
            raise MigrationError("simulated failure")

        monkeypatch.setattr(migrator, "_verify_refs", broken_verify)

        with pytest.raises(MigrationError):
            migrator.migrate("old-slug", "new-slug")

        # Rollback should have restored old-slug
        assert (layout.threads_dir() / "old-slug").is_dir()
        # Manifest should have been restored
        restored = store.read_manifest(sid)
        assert restored is not None
        assert restored.primary_thread == "old-slug"
