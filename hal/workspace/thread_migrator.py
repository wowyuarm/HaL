"""Thread slug migration logic.

Provides ``ThreadSlugMigrator`` which performs an atomic thread-slug rename
across the workspace: thread directory, session manifests, and refs.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from loguru import logger

from hal.domain.session import SessionManifest
from hal.workspace.layout import WorkspaceLayout
from hal.workspace.session_store import SessionStore


class MigrationError(Exception):
    """Raised when a thread-slug migration cannot proceed or fails."""


class MigrationConflict(MigrationError):
    """Raised when active sessions still reference the old slug."""


class ThreadSlugMigrator:
    """Perform a safe thread-slug migration with pre-check, backup, and rollback."""

    def __init__(self, layout: WorkspaceLayout) -> None:
        self.layout = layout
        self._store = SessionStore(layout)

    # -- public API ----------------------------------------------------------

    def migrate(self, old_slug: str, new_slug: str) -> None:
        """Execute the full migration pipeline.

        Steps:
        1. Pre-check for active session conflicts.
        2. Backup thread directory and affected manifests.
        3. Move thread directory.
        4. Update all session manifests.
        5. Verify refs path.
        6. Post-check for residual references.

        On any failure after backup, attempts rollback from the backup snapshot.
        """
        if old_slug == new_slug:
            raise MigrationError("old_slug and new_slug must differ")

        if not self._thread_dir(old_slug).is_dir():
            raise MigrationError(f"Thread directory does not exist: {old_slug}")

        if self._thread_dir(new_slug).exists():
            raise MigrationError(f"Target thread directory already exists: {new_slug}")

        # 1. Pre-check
        conflicts = self._find_active_conflicts(old_slug)
        if conflicts:
            session_ids = ", ".join(c.session_id for c in conflicts)
            raise MigrationConflict(
                f"Active sessions still reference slug {old_slug!r}: {session_ids}"
            )

        # 2. Backup
        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
        backup_dir = self.layout.tmp_dir() / f"slug-migration-{ts}"
        backup_dir.mkdir(parents=True, exist_ok=True)

        try:
            self._backup_thread_dir(old_slug, backup_dir)
            affected = self._find_affected_manifests(old_slug)
            manifest_backup = self._backup_manifests(affected, backup_dir)

            # 3. Move thread directory
            self._move_thread_dir(old_slug, new_slug)

            try:
                # 4. Update manifests
                self._update_manifests(affected, old_slug, new_slug)

                # 5. Verify refs
                self._verify_refs(new_slug)

                # 6. Post-check
                residuals = self._find_residual_refs(old_slug)
                if residuals:
                    session_ids = ", ".join(residuals)
                    raise MigrationError(
                        f"Residual references to {old_slug!r} remain in: {session_ids}"
                    )
            except Exception as exc:
                if not isinstance(exc, MigrationError):
                    exc = MigrationError(f"Migration failed during update: {exc}")
                # Attempt rollback
                try:
                    self._rollback(backup_dir, old_slug, new_slug, manifest_backup)
                except Exception as rb_exc:
                    logger.critical(
                        "Rollback also failed after migration error: {}. "
                        "Backup preserved at: {}",
                        rb_exc,
                        backup_dir,
                    )
                raise

            # Cleanup backup on success
            shutil.rmtree(backup_dir, ignore_errors=True)
            logger.info(
                "Thread slug migrated: {} -> {}", old_slug, new_slug
            )

        except Exception as exc:
            raise MigrationError(
                f"Migration failed. Backup at: {backup_dir}"
            ) from exc

    # -- pre-check -----------------------------------------------------------

    def _find_active_conflicts(self, old_slug: str) -> list[SessionManifest]:
        """Return active session manifests that reference old_slug."""
        return [
            m
            for m in self._store.list_sessions(status="active")
            if _manifest_references_thread(m, old_slug)
        ]

    def _find_affected_manifests(self, old_slug: str) -> list[SessionManifest]:
        """Return all non-archived manifests that reference old_slug."""
        return [
            m
            for m in self._store.list_sessions(include_archived=False)
            if _manifest_references_thread(m, old_slug)
        ]

    def _find_residual_refs(self, old_slug: str) -> list[str]:
        """Return session IDs that still reference old_slug after migration."""
        return [
            m.session_id
            for m in self._store.list_sessions(include_archived=True)
            if _manifest_references_thread(m, old_slug)
        ]

    # -- backup --------------------------------------------------------------

    def _backup_thread_dir(self, slug: str, backup_dir: Path) -> Path:
        src = self._thread_dir(slug)
        dst = backup_dir / f"thread-{slug}"
        shutil.copytree(str(src), str(dst))
        return dst

    def _backup_manifests(
        self, manifests: list[SessionManifest], backup_dir: Path
    ) -> list[tuple[str, Path]]:
        """Backup manifests; return list of (session_id, backup_path)."""
        result: list[tuple[str, Path]] = []
        for m in manifests:
            src = self._store.manifest_path(m.session_id)
            if not src.is_file():
                continue
            dst = backup_dir / f"manifest-{m.session_id}.json"
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            result.append((m.session_id, dst))
        return result

    # -- migration steps -----------------------------------------------------

    def _move_thread_dir(self, old_slug: str, new_slug: str) -> None:
        src = self._thread_dir(old_slug)
        dst = self._thread_dir(new_slug)
        shutil.move(str(src), str(dst))

    def _update_manifests(
        self, manifests: list[SessionManifest], old_slug: str, new_slug: str
    ) -> None:
        for m in manifests:
            updated = _replace_slug_in_manifest(m, old_slug, new_slug)
            self._store.write_manifest(m.session_id, updated)

    def _verify_refs(self, new_slug: str) -> None:
        refs_dir = self.layout.thread_refs_dir(new_slug)
        if not refs_dir.is_dir():
            raise MigrationError(
                f"Refs directory not found after migration: {refs_dir}"
            )

    # -- rollback ------------------------------------------------------------

    def _rollback(
        self,
        backup_dir: Path,
        old_slug: str,
        new_slug: str,
        manifest_backup: list[tuple[str, Path]],
    ) -> None:
        logger.warning("Rolling back thread slug migration")

        # Restore thread directory
        backup_thread = backup_dir / f"thread-{old_slug}"
        target_thread = self._thread_dir(new_slug)
        if target_thread.exists():
            shutil.rmtree(target_thread)
        if backup_thread.is_dir():
            shutil.copytree(str(backup_thread), str(target_thread))
            shutil.move(str(target_thread), str(self._thread_dir(old_slug)))

        # Restore manifests
        for session_id, backup_path in manifest_backup:
            if backup_path.is_file():
                original = self._store.manifest_path(session_id)
                original.write_text(
                    backup_path.read_text(encoding="utf-8"), encoding="utf-8"
                )

    # -- helpers -------------------------------------------------------------

    def _thread_dir(self, slug: str) -> Path:
        return self.layout.threads_dir() / slug


def _manifest_references_thread(manifest: SessionManifest, slug: str) -> bool:
    """Check whether a manifest references a given thread slug."""
    if manifest.primary_thread == slug:
        return True
    if slug in manifest.mounted_threads:
        return True
    if slug in manifest.touched_threads:
        return True
    return False


def _replace_slug_in_manifest(
    manifest: SessionManifest, old_slug: str, new_slug: str
) -> SessionManifest:
    """Return a new manifest with old_slug replaced by new_slug."""
    updated = manifest.model_copy()
    if updated.primary_thread == old_slug:
        updated.primary_thread = new_slug
    if old_slug in updated.mounted_threads:
        updated.mounted_threads = sorted(
            [new_slug if s == old_slug else s for s in updated.mounted_threads]
        )
    if old_slug in updated.touched_threads:
        updated.touched_threads = sorted(
            [new_slug if s == old_slug else s for s in updated.touched_threads]
        )
    return updated
