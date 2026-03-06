"""Runtime loop-execution orchestration facade."""

from __future__ import annotations

from typing import Any


async def execute_loop(
    engine: Any,
    *,
    messages: list[dict[str, Any]],
    max_iterations: int,
    add_assistant_message_fn: Any,
    add_tool_result_fn: Any,
    session_key: str | None = None,
    channel: str | None = None,
    chat_id: str | None = None,
) -> tuple[str | None, Any, list[Any]]:
    """Execute one tool-calling loop iteration sequence."""
    from .execution_flow import execute_loop as _execute_loop

    return await _execute_loop(
        engine,
        messages=messages,
        max_iterations=max_iterations,
        add_assistant_message_fn=add_assistant_message_fn,
        add_tool_result_fn=add_tool_result_fn,
        session_key=session_key,
        channel=channel,
        chat_id=chat_id,
    )


__all__ = ["execute_loop"]
