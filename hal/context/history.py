"""History loading and persistence helpers for compiled working sets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from hal.context.message_building import copy_history_without_session_baseline


@dataclass(frozen=True, slots=True)
class LoadedHistory:
    """Resolved history inputs for one compiled or inspected session turn."""

    messages: list[dict[str, object]]
    using_session_history: bool
    history_window: list[dict[str, Any]]


def load_history_for_context(
    *,
    session_history: list[dict[str, object]] | None,
    memory: Any,
    history_config: Any,
    channel: str,
    chat_id: str,
    token_model: str,
) -> LoadedHistory:
    """Resolve history source for one context compilation or inspection request."""
    if session_history is not None:
        return _load_session_history(session_history)
    return _load_memory_history(
        memory=memory,
        history_config=history_config,
        channel=channel,
        chat_id=chat_id,
        token_model=token_model,
    )


def _load_session_history(session_history: list[dict[str, object]]) -> LoadedHistory:
    """Wrap already-materialized session history into the shared container."""
    return LoadedHistory(
        messages=list(session_history),
        using_session_history=True,
        history_window=[],
    )


def _load_memory_history(
    *,
    memory: Any,
    history_config: Any,
    channel: str,
    chat_id: str,
    token_model: str,
) -> LoadedHistory:
    """Load history from memory storage plus a lightweight daily-log window view."""
    history = memory.get_conversation_history(
        channel=channel,
        chat_id=chat_id,
        max_messages=history_config.max_messages,
        include_tools=False,
        recent_full_turns=history_config.recent_full_turns,
        assistant_truncate_tokens=history_config.assistant_truncate_tokens,
        max_tokens=history_config.max_history_tokens,
        history_days=history_config.history_days,
        token_model=token_model,
    )
    return LoadedHistory(
        messages=history,
        using_session_history=False,
        history_window=_build_daily_history_window(memory, history_config=history_config),
    )


def _build_daily_history_window(memory: Any, *, history_config: Any) -> list[dict[str, Any]]:
    """Build the inspect-friendly daily history window when daily logs exist."""
    daily_log = getattr(memory, "daily_log", None)
    data_dir = getattr(daily_log, "data_dir", None)
    if not isinstance(data_dir, Path):
        return []
    return build_history_window(
        history_days=history_config.history_days,
        log_dir=data_dir,
    )


def build_history_window(*, history_days: int, log_dir: Path) -> list[dict[str, Any]]:
    """Build a lightweight view of daily log file presence across the requested window."""
    days = max(history_days, 1)
    today = date.today()
    return [
        {
            "date": (today - timedelta(days=offset)).isoformat(),
            "exists": (log_dir / f"{(today - timedelta(days=offset)).isoformat()}.jsonl").exists(),
        }
        for offset in range(days - 1, -1, -1)
    ]


def build_persisted_session_history(
    *,
    working_set_messages: list[dict[str, object]],
    final_content: str,
    include_final_assistant: bool,
) -> list[dict[str, object]]:
    """Build next in-memory session history from working-set messages and final output."""
    history = copy_history_without_session_baseline(working_set_messages)
    if include_final_assistant:
        history.append({"role": "assistant", "content": final_content})
    return history
