"""Workspace repository for session manifests and append-only per-session event logs.

Each session is stored as a directory under ``work/sessions/{session_id}/``
containing a ``manifest.json`` and a ``working-log.jsonl``. The manifest is
a compact, JSON-serializable summary of session metadata; the working log is
an append-only sequence of ``SessionEvent`` rows that serve as the source of
truth for UI reconstruction, brief input, and audit.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from loguru import logger

from hal.domain.events import SessionEvent
from hal.domain.session import SessionManifest

from .jsonl import append_jsonl_line, read_jsonl_lines
from .layout import WorkspaceLayout


class SessionStore:
    """Filesystem-backed repository for session manifests and working logs."""

    def __init__(self, layout: WorkspaceLayout) -> None:
        self.layout = layout

    @property
    def sessions_root(self) -> Path:
        """Root directory containing all durable session directories."""
        return self.layout.work_sessions_dir()

    def session_dir(self, session_id: str) -> Path:
        return self.layout.session_dir(session_id)

    def manifest_path(self, session_id: str) -> Path:
        return self.layout.session_manifest_path(session_id)

    def log_path(self, session_id: str) -> Path:
        return self.layout.session_log_path(session_id)

    # -- write operations ---------------------------------------------------

    def create(self, session_id: str) -> Path:
        """Create a session directory, returning its path."""
        path = self.session_dir(session_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_manifest(self, session_id: str, manifest: SessionManifest) -> Path:
        """Write (or overwrite) a session manifest.

        Raises ``ValueError`` if the manifest's session_id does not match the
        directory-level session_id, preventing accidental cross-session writes.
        """
        if manifest.session_id != session_id:
            raise ValueError(
                f"manifest session_id {manifest.session_id!r} != path session_id {session_id!r}"
            )
        path = self.manifest_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        return path

    def append_event(self, session_id: str, event: SessionEvent) -> None:
        """Append one event row to the per-session working log."""
        append_jsonl_line(self.log_path(session_id), event.model_dump_json())

    def delete(self, session_id: str) -> None:
        """Delete an entire session directory tree."""
        path = self.session_dir(session_id)
        if path.is_dir():
            shutil.rmtree(path)

    # -- read operations ----------------------------------------------------

    def read_manifest(self, session_id: str) -> SessionManifest | None:
        """Load a session manifest, returning None when absent or invalid."""
        path = self.manifest_path(session_id)
        if not path.is_file():
            return None
        try:
            return SessionManifest.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("failed to read session manifest {}: {}", path, exc)
            return None

    def read_events(self, session_id: str, *, after_seq: int = 0) -> list[SessionEvent]:
        """Read session events, optionally starting after a given sequence number."""
        events: list[SessionEvent] = []
        for raw in read_jsonl_lines(self.log_path(session_id)):
            try:
                event = SessionEvent.model_validate_json(raw)
            except Exception as exc:
                logger.warning("malformed event row in session {}: {}", session_id, exc)
                continue
            if event.seq > after_seq:
                events.append(event)
        return events

    def list_sessions(
        self,
        *,
        thread_slug: str | None = None,
        status: str | None = None,
    ) -> list[SessionManifest]:
        """List session manifests, optionally filtered by thread or status.

        Directories are sorted lexicographically, which produces chronological
        order because session IDs embed a timestamp prefix.
        """
        if not self.sessions_root.is_dir():
            return []

        results: list[SessionManifest] = []
        for entry in sorted(self.sessions_root.iterdir()):
            if not entry.is_dir():
                continue
            manifest = self.read_manifest(entry.name)
            if manifest is None:
                continue
            if status is not None and manifest.status != status:
                continue
            if thread_slug is not None and not _matches_thread(manifest, thread_slug):
                continue
            results.append(manifest)
        return results


def _matches_thread(manifest: SessionManifest, slug: str) -> bool:
    """Check whether a manifest references the given thread in any scope."""
    if manifest.primary_thread == slug:
        return True
    return slug in manifest.mounted_threads or slug in manifest.touched_threads
