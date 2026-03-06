"""Main tool-loop execution helpers for AgentEngine."""

from __future__ import annotations

from typing import Any

from hal.core.engine.hooks import _EngineLoopHooks
from hal.core.runtime.loop import run_tool_loop


async def execute_loop(
    engine: Any,
    *,
    messages: list[dict[str, object]],
    max_iterations: int,
    add_assistant_message_fn: Any,
    add_tool_result_fn: Any,
    session_key: str | None = None,
    channel: str | None = None,
    chat_id: str | None = None,
) -> tuple[str | None, object, list[object]]:
    """Run one LLM tool-calling loop and collect injected follow-up messages."""
    hooks = _EngineLoopHooks(
        engine=engine,
        session_key=session_key,
        channel=channel,
        chat_id=chat_id,
    )
    try:
        final_content, meta = await run_tool_loop(
            provider=engine.provider,
            model=engine.model,
            tools=engine.tools,
            messages=messages,
            max_iterations=max_iterations,
            hooks=hooks,
            add_assistant_message=add_assistant_message_fn,
            add_tool_result=add_tool_result_fn,
            llm_retry_attempts=engine._engine_config.llm_retry_attempts,
            llm_retry_base_delay_s=engine._engine_config.llm_retry_base_delay_s,
            llm_retry_max_delay_s=engine._engine_config.llm_retry_max_delay_s,
        )
        return final_content, meta, hooks.injected
    finally:
        hooks.close()


__all__ = ["execute_loop"]
