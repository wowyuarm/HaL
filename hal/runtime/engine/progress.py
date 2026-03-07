"""Progress message formatting helpers for tool execution."""

from __future__ import annotations

import re
from typing import Any

_THINK_RE = re.compile(r"<think>.*?</think>|<think>.*$", re.DOTALL)


def _extract_progress_text(
    assistant_content: str | None,
) -> str | None:
    """Extract a clean assistant intent line for interim progress display."""
    if not assistant_content:
        return None

    cleaned = _THINK_RE.sub("", assistant_content).strip()
    return cleaned or None


def _format_tool_hints(tool_calls: list[Any]) -> list[str]:
    """Format tool-call hints for interim progress display."""
    hints: list[str] = []
    for tc in tool_calls or []:
        summary = _summarize_args(tc.arguments)
        hints.append(f"↳ {tc.name}({summary})")
    return hints


def _compose_progress_message(
    progress_text: str | None,
    tool_hints: list[str],
    *,
    send_progress: bool,
    send_tool_hints: bool,
) -> str | None:
    """Compose the interim progress message according to channel policy."""
    parts: list[str] = []
    if send_progress and progress_text:
        parts.append(progress_text)
    if send_tool_hints and tool_hints:
        parts.extend(tool_hints)
    return "\n".join(parts) if parts else None


def _summarize_args(args: dict[str, Any] | None) -> str:
    """Produce a short argument summary for progress display."""
    if not args:
        return ""

    for key in ("query", "task", "command", "path", "url", "content", "pattern"):
        if key in args:
            val = str(args[key])
            if len(val) > 60:
                val = val[:57] + "..."
            return repr(val)

    first_val = str(next(iter(args.values())))
    if len(first_val) > 60:
        first_val = first_val[:57] + "..."
    return repr(first_val)
