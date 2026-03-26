"""Domain session models and identity helpers.

A session is a first-class work unit mounted on one or more threads. Its
manifest is persisted to ``work/sessions/{session_id}/manifest.json``; its
runtime state lives in engine memory for the duration of the session.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .event_sink import SessionEventPublisher

# ---------------------------------------------------------------------------
# Identity helpers
# ---------------------------------------------------------------------------

_SESSION_ID_HEX_LEN = 8
_TURN_ID_WIDTH = 4


def build_session_id() -> str:
    """Build a compact, sortable session identifier (``s_YYYYMMDDHHmmss_<hex8>``)."""
    now = datetime.now()
    suffix = uuid.uuid4().hex[:_SESSION_ID_HEX_LEN]
    return f"s_{now.strftime('%Y%m%d%H%M%S')}_{suffix}"


def build_turn_id(turn_count: int) -> str:
    """Build a zero-padded turn identifier (``t_NNNN``)."""
    return f"t_{turn_count:0{_TURN_ID_WIDTH}d}"


# ---------------------------------------------------------------------------
# Persistent manifest (JSON-serializable)
# ---------------------------------------------------------------------------

SessionStatus = Literal["active", "briefing", "ended", "dropped"]


class SessionManifest(BaseModel):
    """Durable session metadata persisted alongside the working log.

    ``mounted_threads`` and ``touched_threads`` are stored as sorted lists for
    deterministic JSON serialisation; convert to ``set`` in runtime state.
    """

    session_id: str
    status: SessionStatus = "active"
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    ended_at: str | None = None
    channel: str | None = None
    chat_id: str | None = None
    primary_thread: str | None = None
    title: str | None = None
    mounted_threads: list[str] = Field(default_factory=list)
    touched_threads: list[str] = Field(default_factory=list)
    turn_count: int = 0
    last_event_seq: int = 0
    brief_prompt: str | None = None
    archived_at: str | None = None


# ---------------------------------------------------------------------------
# In-memory runtime state
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SessionRuntimeState:
    """Mutable runtime state associated with one active session.

    Pairs a persistent ``SessionManifest`` with ephemeral engine bookkeeping
    that does not survive a restart.
    """

    manifest: SessionManifest
    last_activity_at: datetime
    event_publisher: SessionEventPublisher
    replay_history: list[dict[str, object]] = field(default_factory=list)
    context_hint_keys: set[str] = field(default_factory=set)
    brief_task: asyncio.Task[None] | None = None

    # -- convenience proxies ------------------------------------------------

    @property
    def session_id(self) -> str:
        return self.manifest.session_id

    @property
    def primary_thread(self) -> str | None:
        return self.manifest.primary_thread

    @property
    def mounted_threads(self) -> set[str]:
        return set(self.manifest.mounted_threads)

    @property
    def touched_threads(self) -> set[str]:
        return set(self.manifest.touched_threads)

    def touch_thread(self, slug: str) -> None:
        """Record that a thread was accessed during this session."""
        threads = set(self.manifest.touched_threads)
        if slug not in threads:
            threads.add(slug)
            self.manifest.touched_threads = sorted(threads)

    def mount_thread(self, slug: str) -> None:
        """Add a thread to the mounted set."""
        threads = set(self.manifest.mounted_threads)
        if slug not in threads:
            threads.add(slug)
            self.manifest.mounted_threads = sorted(threads)

    def unmount_thread(self, slug: str) -> None:
        """Remove a thread from the mounted set."""
        threads = set(self.manifest.mounted_threads)
        threads.discard(slug)
        self.manifest.mounted_threads = sorted(threads)

    def set_primary_thread(self, slug: str | None) -> None:
        """Change the primary thread. Also auto-mounts it when non-None."""
        self.manifest.primary_thread = slug
        if slug is not None:
            self.mount_thread(slug)
