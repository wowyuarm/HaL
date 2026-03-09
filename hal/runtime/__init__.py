"""Runtime components and facades for loop/session/brief orchestration."""

from .brief import (
    extract_touched_threads,
    format_session_events_for_prompt,
    resolve_brief_thread_order,
    run_session_brief,
)
from .loop import LoopHooks, LoopMetadata, run_tool_loop
from .session import (
    build_session_id,
    build_session_snapshot_messages,
    ensure_session_state,
    generate_session_checkpoint,
    maybe_compact_session_history,
    tick_session_lifecycle,
    touch_session,
)
from .tool_factory import create_tools

__all__ = [
    "LoopHooks",
    "LoopMetadata",
    "build_session_id",
    "build_session_snapshot_messages",
    "create_tools",
    "ensure_session_state",
    "extract_touched_threads",
    "format_session_events_for_prompt",
    "generate_session_checkpoint",
    "maybe_compact_session_history",
    "resolve_brief_thread_order",
    "run_session_brief",
    "run_tool_loop",
    "tick_session_lifecycle",
    "touch_session",
]
