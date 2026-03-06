"""Runtime session orchestration facade."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .session_flow import build_session_id as _build_session_id
from .session_flow import ensure_session_state as _ensure_session_state
from .session_flow import maybe_compact_session_history as _maybe_compact_session_history
from .session_flow import tick_session_lifecycle as _tick_session_lifecycle
from .session_flow import touch_session as _touch_session


def build_session_id(*, now: datetime | None = None) -> str:
    """Build a compact, sortable session identifier."""
    return _build_session_id(now=now)


def ensure_session_state(engine: Any, *, session_key: str, channel: str, chat_id: str) -> Any:
    """Ensure one session state exists for the requested scope."""
    return _ensure_session_state(engine, session_key=session_key, channel=channel, chat_id=chat_id)


def touch_session(engine: Any, session_key: str) -> None:
    """Touch one session state to refresh last-activity timestamp."""
    _touch_session(engine, session_key)


async def maybe_compact_session_history(
    engine: Any,
    *,
    session_key: str,
    history: list[dict[str, object]],
    token_model: str | None,
) -> list[dict[str, object]]:
    """Compact one session history snapshot when budget thresholds are exceeded."""
    return await _maybe_compact_session_history(
        engine,
        session_key=session_key,
        history=history,
        token_model=token_model,
    )


async def tick_session_lifecycle(engine: Any) -> None:
    """Run one session-lifecycle tick across active runtime sessions."""
    await _tick_session_lifecycle(engine)


__all__ = [
    "build_session_id",
    "ensure_session_state",
    "maybe_compact_session_history",
    "tick_session_lifecycle",
    "touch_session",
]
