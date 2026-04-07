"""Workspace repository for session manifests and append-only per-session event logs.

Each session is stored as a directory under ``work/sessions/{session_id}/``
containing a ``manifest.json`` and a ``working-log.jsonl``. The manifest is
a compact, JSON-serializable summary of session metadata; the working log is
an append-only sequence of ``SessionEvent`` rows that serve as the source of
truth for UI reconstruction, brief input, and audit.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import TypeAlias

from loguru import logger

from hal.domain.events import SessionEvent
from hal.domain.session import SessionManifest

from .jsonl import append_jsonl_line, read_jsonl_lines
from .layout import WorkspaceLayout

FileState: TypeAlias = tuple[int | None, int | None]
SessionEventsCacheEntry: TypeAlias = tuple[int | None, int | None, list[SessionEvent]]


class SessionStore:
    """Filesystem-backed repository for session manifests and working logs."""

    def __init__(self, layout: WorkspaceLayout) -> None:
        self.layout = layout
        self._events_cache: dict[str, SessionEventsCacheEntry] = {}

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
        self._events_cache.pop(session_id, None)

    def archive(self, session_id: str) -> SessionManifest | None:
        """Mark one terminal session archived and persist the manifest."""
        manifest = self.read_manifest(session_id)
        if manifest is None:
            return None
        if manifest.status not in {"ended", "dropped"}:
            raise ValueError(
                f"Session {session_id} is not archivable (status={manifest.status})"
            )
        if manifest.archived_at:
            return manifest
        manifest.archived_at = datetime.now().isoformat()
        self.write_manifest(session_id, manifest)
        return manifest

    def restore(self, session_id: str) -> SessionManifest | None:
        """Clear archive marker for one session and persist the manifest."""
        manifest = self.read_manifest(session_id)
        if manifest is None:
            return None
        if not manifest.archived_at:
            return manifest
        manifest.archived_at = None
        self.write_manifest(session_id, manifest)
        return manifest

    def delete(self, session_id: str) -> None:
        """Delete an entire session directory tree."""
        path = self.session_dir(session_id)
        if path.is_dir():
            shutil.rmtree(path)
        self._events_cache.pop(session_id, None)

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
        events = self._read_cached_events(session_id)
        if after_seq <= 0:
            return list(events)
        return [event for event in events if event.seq > after_seq]

    def _read_cached_events(self, session_id: str) -> list[SessionEvent]:
        path = self.log_path(session_id)
        state = _file_state(path)
        cached = self._events_cache.get(session_id)
        if cached is not None and cached[:2] == state:
            return cached[2]

        events: list[SessionEvent] = []
        for raw in read_jsonl_lines(path):
            try:
                event = SessionEvent.model_validate_json(raw)
            except Exception as exc:
                logger.warning("malformed event row in session {}: {}", session_id, exc)
                continue
            events.append(event)

        self._events_cache[session_id] = (*state, events)
        return events

    def list_sessions(
        self,
        *,
        thread_slug: str | None = None,
        status: str | None = None,
        include_archived: bool = False,
    ) -> list[SessionManifest]:
        """List session manifests, optionally filtered by current thread scope or status.

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
            if not include_archived and manifest.archived_at is not None:
                continue
            if status is not None and manifest.status != status:
                continue
            if thread_slug is not None and not _matches_thread(manifest, thread_slug):
                continue
            results.append(manifest)
        return results


def _matches_thread(manifest: SessionManifest, slug: str) -> bool:
    """Check whether a manifest is currently mounted on the given thread."""
    if manifest.primary_thread == slug:
        return True
    return slug in manifest.mounted_threads


def _file_state(path: Path) -> FileState:
    """Return the file state used to validate read caches."""
    if not path.is_file():
        return (None, None)
    stat = path.stat()
    return (stat.st_mtime_ns, stat.st_size)
