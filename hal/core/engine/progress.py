"""Progress message formatting helpers for tool execution."""

from __future__ import annotations

import re
from typing import Any

_THINK_RE = re.compile(r"<think>.*?</think>|<think>.*$", re.DOTALL)


def _format_progress_message(
    assistant_content: str | None,
    tool_calls: list[Any],
) -> str | None:
    """Build a progress message combining intent and tool calls."""
    parts: list[str] = []

    if assistant_content:
        cleaned = _THINK_RE.sub("", assistant_content).strip()
        if cleaned:
            parts.append(cleaned)

    for tc in tool_calls or []:
        summary = _summarize_args(tc.arguments)
        parts.append(f"↳ {tc.name}({summary})")

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
