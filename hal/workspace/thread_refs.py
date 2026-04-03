"""Per-thread session reference index.

Each thread maintains a ``refs/sessions.jsonl`` file listing sessions that
were associated with it (as primary, mounted, touched, or related). This reverse index allows
the thread view to enumerate its sessions without scanning every session
manifest on disk.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from loguru import logger
from pydantic import BaseModel, Field

from .jsonl import append_jsonl_line, read_jsonl_lines
from .layout import WorkspaceLayout

_REFS_FILENAME = "sessions.jsonl"


class ThreadSessionRef(BaseModel):
    """One thread-to-session reference row."""

    session_id: str
    ts: str = Field(default_factory=lambda: datetime.now().isoformat())
    role: Literal["primary", "mounted", "touched", "related", "created"]


class ThreadRefsRepository:
    """Append-only repository for per-thread session references."""

    def __init__(self, layout: WorkspaceLayout) -> None:
        self.layout = layout

    def refs_path(self, thread_slug: str) -> Path:
        """Resolve the sessions reference log for one thread."""
        return self.layout.thread_refs_dir(thread_slug) / _REFS_FILENAME

    def append_ref(self, thread_slug: str, ref: ThreadSessionRef) -> None:
        """Append one session reference row to a thread's refs log."""
        append_jsonl_line(self.refs_path(thread_slug), ref.model_dump_json())

    def read_refs(self, thread_slug: str) -> list[ThreadSessionRef]:
        """Read all session references recorded for one thread."""
        refs: list[ThreadSessionRef] = []
        for raw in read_jsonl_lines(self.refs_path(thread_slug)):
            try:
                refs.append(ThreadSessionRef.model_validate_json(raw))
            except Exception as exc:
                logger.warning("invalid thread session ref for {}: {}", thread_slug, exc)
        return refs
