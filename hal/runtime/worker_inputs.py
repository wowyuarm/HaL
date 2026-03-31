"""Shared worker-input rendering for session events and dialogue history."""

from __future__ import annotations

from typing import Any

from hal.context.token_budget import estimate_text_tokens, trim_text_to_token_budget
from hal.domain.events import SessionEvent
from hal.domain.message_payloads import render_message_payload_summary


def cap_text_to_tokens(
    text: str,
    *,
    max_tokens: int,
    model: str | None = None,
    suffix: str = "...[truncated]",
) -> str:
    """Trim text to *max_tokens* when needed."""
    if max_tokens <= 0:
        return text
    if estimate_text_tokens(text, model=model) <= max_tokens:
        return text
    return trim_text_to_token_budget(text, max_tokens, model=model, suffix=suffix)


def render_lines_with_token_budget(
    lines: list[str],
    *,
    max_line_tokens: int,
    max_total_tokens: int,
    model: str | None = None,
    line_suffix: str = "...[truncated]",
    total_suffix: str = "...[truncated]",
) -> str:
    """Cap each line and then cap the whole joined output by token budget."""
    if not lines:
        return ""
    capped_lines = [
        cap_text_to_tokens(
            line,
            max_tokens=max_line_tokens,
            model=model,
            suffix=line_suffix,
        )
        for line in lines
    ]
    rendered = "\n".join(capped_lines)
    return cap_text_to_tokens(
        rendered,
        max_tokens=max_total_tokens,
        model=model,
        suffix=total_suffix,
    )


def render_worker_input_lines(
    lines: list[str],
    *,
    model: str | None,
    max_line_tokens: int,
    max_total_tokens: int,
    empty_text: str,
    line_suffix: str = "...[truncated]",
    total_suffix: str = "...[truncated]",
) -> str:
    """Apply shared token budgets to worker-input lines."""
    if not lines:
        return empty_text
    return render_lines_with_token_budget(
        lines,
        max_line_tokens=max_line_tokens,
        max_total_tokens=max_total_tokens,
        model=model,
        line_suffix=line_suffix,
        total_suffix=total_suffix,
    )


def build_event_input_lines(events: list[SessionEvent]) -> list[str]:
    """Build one-line event records for worker consumption."""
    lines: list[str] = []
    for event in events:
        preview = _event_preview(event.payload or {})
        lines.append(f"- [{event.ts}] {event.type}: {preview}")
    return lines


def build_history_input_lines(messages: list[dict[str, Any]]) -> list[str]:
    """Build compact dialogue records for worker consumption."""
    lines: list[str] = []
    for idx, message in enumerate(messages, 1):
        role = str(message.get("role", ""))
        rendered = render_message_payload_summary(
            message,
            max_content_chars=None,
            max_reasoning_chars=None,
            max_tool_args_chars=None,
        )
        block = f"[{idx}] {role}".strip()
        if rendered:
            block += f"\n{rendered}"
        lines.append(block)
    return lines


def _event_preview(payload: dict[str, Any]) -> str:
    if not payload:
        return "(empty)"

    tool_name = payload.get("tool")
    if isinstance(tool_name, str) and tool_name.strip():
        result_preview = payload.get("result_preview", "")
        if isinstance(result_preview, str) and result_preview.strip():
            return f"{tool_name} \u2192 {result_preview.strip()}".replace("\n", " ")
        return tool_name.strip()

    for key in ("content", "label", "status"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().replace("\n", " ")
    return str(payload)


__all__ = [
    "build_event_input_lines",
    "build_history_input_lines",
    "cap_text_to_tokens",
    "render_lines_with_token_budget",
    "render_worker_input_lines",
]
