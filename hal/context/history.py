"""History loading and persistence helpers for compiled working sets."""

from __future__ import annotations

from dataclasses import dataclass

from hal.context.message_building import copy_history_without_session_baseline


@dataclass(frozen=True, slots=True)
class LoadedHistory:
    """Resolved history inputs for one compiled or inspected session turn."""

    messages: list[dict[str, object]]
    using_session_history: bool


def load_history_for_context(
    *,
    session_history: list[dict[str, object]] | None,
    **_kwargs: object,
) -> LoadedHistory:
    """Resolve history source for one context compilation or inspection request.

    Session history is always available in the current architecture (in-memory).
    The kwargs sink absorbs legacy caller parameters for backward compatibility.
    """
    messages = list(session_history) if session_history is not None else []
    return LoadedHistory(
        messages=messages,
        using_session_history=session_history is not None,
    )


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
