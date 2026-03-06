"""Runtime session-snapshot assembly facade."""

from __future__ import annotations

from typing import Any

from .snapshot_flow import build_session_snapshot_messages as _build_session_snapshot_messages


def build_session_snapshot_messages(
    engine: Any,
    *,
    session_key: str,
    channel: str | None = None,
    chat_id: str | None = None,
    token_model: str | None = None,
) -> list[dict[str, object]]:
    """Build one persisted session snapshot message list."""
    _ = channel, chat_id
    return _build_session_snapshot_messages(
        engine,
        session_key=session_key,
        token_model=token_model,
    )


__all__ = ["build_session_snapshot_messages"]
