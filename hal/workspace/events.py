"""Workspace-facing repository for append-only session events."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, TypeAlias

from pydantic import BaseModel, Field

from .jsonl import append_jsonl_line, read_jsonl_lines
from .layout import WorkspaceLayout

FileEventsCacheEntry: TypeAlias = tuple[int | None, int | None, list["EventEntry"]]


class EventEntry(BaseModel):
    """A single event row in the unified workspace event log."""

    ts: str = Field(default_factory=lambda: datetime.now().isoformat())
    session: str
    type: str
    channel: str | None = None
    chat_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class EventLogRepository:
    """Append-only JSONL repository for workspace session events."""

    def __init__(self, workspace: Path):
        self.layout = WorkspaceLayout(workspace)
        self.file_path = self.layout.events_log_path()
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._session_cache: dict[str, FileEventsCacheEntry] = {}

    def append(
        self,
        *,
        session: str,
        event_type: str,
        channel: str | None = None,
        chat_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> EventEntry:
        """Append one structured event row to the unified event log."""
        entry = EventEntry(
            session=session,
            type=event_type,
            channel=channel,
            chat_id=chat_id,
            payload=payload or {},
        )
        append_jsonl_line(self.file_path, entry.model_dump_json())
        self._session_cache.clear()
        return entry

    def read_session(self, session_id: str) -> list[EventEntry]:
        """Load all recorded events for one session id."""
        state = _file_state(self.file_path)
        cached = self._session_cache.get(session_id)
        if cached is not None and cached[:2] == state:
            return list(cached[2])

        rows: list[EventEntry] = []
        for raw in read_jsonl_lines(self.file_path):
            try:
                entry = EventEntry.model_validate_json(raw)
            except Exception:
                continue
            if entry.session == session_id:
                rows.append(entry)

        self._session_cache[session_id] = (*state, rows)
        return list(rows)


def _file_state(path: Path) -> tuple[int | None, int | None]:
    """Return the file state used to validate read caches."""
    if not path.is_file():
        return (None, None)
    stat = path.stat()
    return (stat.st_mtime_ns, stat.st_size)
