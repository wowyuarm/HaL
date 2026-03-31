"""Runtime components and facades for loop/session/brief orchestration."""

from hal.domain.session import SessionRuntimeState

from .brief import (
    extract_touched_threads,
    format_session_events_for_prompt,
    resolve_brief_thread_order,
    run_session_brief,
)
from .loop import LoopHooks, LoopMetadata, run_tool_loop
from .session import (
    build_session_snapshot_messages,
    compact_full_session_history,
    generate_session_checkpoint,
    maybe_compact_session_history,
    tick_session_lifecycle,
)
from .tool_factory import create_tools

__all__ = [
    "LoopHooks",
    "LoopMetadata",
    "SessionRuntimeState",
    "build_session_snapshot_messages",
    "compact_full_session_history",
    "create_tools",
    "extract_touched_threads",
    "format_session_events_for_prompt",
    "generate_session_checkpoint",
    "maybe_compact_session_history",
    "resolve_brief_thread_order",
    "run_session_brief",
    "run_tool_loop",
    "tick_session_lifecycle",
]
