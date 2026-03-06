"""Forward-compatible runtime package surface.

This module provides a stable import path (`hal.runtime`) while implementation
continues to live under `hal.core.runtime` during staged package reorganization.
"""

from __future__ import annotations

from hal.core.runtime import (
    LoopHooks,
    LoopMetadata,
    build_session_id,
    build_session_snapshot_messages,
    create_tools,
    ensure_session_state,
    execute_loop,
    generate_episode_markdown,
    generate_session_checkpoint,
    generate_summary,
    maybe_compact_session_history,
    resolve_debrief_thread_order,
    resolve_summary_model_id,
    run_session_debrief,
    run_tool_loop,
    tick_session_lifecycle,
    touch_session,
    trigger_summary_task,
)

__all__ = [
    "LoopMetadata",
    "LoopHooks",
    "build_session_id",
    "build_session_snapshot_messages",
    "create_tools",
    "ensure_session_state",
    "execute_loop",
    "generate_episode_markdown",
    "generate_session_checkpoint",
    "generate_summary",
    "maybe_compact_session_history",
    "resolve_summary_model_id",
    "resolve_debrief_thread_order",
    "run_tool_loop",
    "run_session_debrief",
    "tick_session_lifecycle",
    "touch_session",
    "trigger_summary_task",
]
