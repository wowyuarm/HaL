"""Helpers for assembling session working-set message sequences."""

from __future__ import annotations

from hal.core.context.session_messages import is_session_baseline_content


def build_system_message(system_prompt: str) -> dict[str, object]:
    """Wrap rendered system prompt text into one system-role message."""
    return {"role": "system", "content": system_prompt}


def assemble_message_sequence(
    *,
    system_message: dict[str, object],
    history: list[dict[str, object]] | None = None,
    session_baseline: dict[str, object] | None = None,
    user_message: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    """Assemble a working-set message sequence from stable and optional layers."""
    messages: list[dict[str, object]] = [system_message]
    if session_baseline is not None:
        messages.append(session_baseline)
    if history:
        messages.extend(history)
    if user_message is not None:
        messages.append(user_message)
    return messages


def copy_history_without_session_baseline(
    messages: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Copy history messages while dropping the synthetic session-baseline block."""
    return [
        dict(item) for item in messages[1:] if not is_session_baseline_content(item.get("content"))
    ]
