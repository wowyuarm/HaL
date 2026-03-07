"""Runtime session state object for AgentEngine."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class SessionState:
    """Runtime session state for one channel/chat scope."""

    session_id: str
    channel: str
    chat_id: str
    started_at: datetime
    last_activity_at: datetime
    baseline_context: str | None = None
    baseline_thread_slugs: set[str] = field(default_factory=set)
    history: list[dict[str, object]] = field(default_factory=list)
    touched_threads: set[str] = field(default_factory=set)
    context_advisor_started: bool = False
    context_hint_keys: set[str] = field(default_factory=set)
    awaiting_debrief_confirmation: bool = False
    debrief_confirm_deadline: datetime | None = None
    debrief_task: asyncio.Task[None] | None = None


__all__ = ["SessionState"]
