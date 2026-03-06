"""Runtime components and facades for loop/session/debrief orchestration."""

from .checkpoint import generate_session_checkpoint
from .debrief import (
    generate_episode_markdown,
    resolve_debrief_thread_order,
    run_session_debrief,
)
from .execution import execute_loop
from .loop import LoopHooks, LoopMetadata, run_tool_loop
from .session import (
    build_session_id,
    ensure_session_state,
    maybe_compact_session_history,
    tick_session_lifecycle,
    touch_session,
)
from .snapshot import build_session_snapshot_messages
from .summary import generate_summary
from .summary_flow import resolve_summary_model_id, trigger_summary_task
from .tool_factory import create_tools

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
