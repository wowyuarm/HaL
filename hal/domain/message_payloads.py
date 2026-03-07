"""Shared helpers for building and summarizing LLM message payloads."""

from __future__ import annotations

from typing import Any

_MAX_TOOL_CALLS_TO_RENDER = 6
_TRUNCATION_SUFFIX = "..."


def build_assistant_message_payload(
    *,
    content: str | None,
    tool_calls: list[dict[str, Any]] | None = None,
    reasoning_content: str | None = None,
) -> dict[str, Any]:
    """Build canonical assistant message payload with optional metadata."""
    message: dict[str, Any] = {"role": "assistant", "content": content or ""}
    if tool_calls:
        message["tool_calls"] = tool_calls
    if reasoning_content:
        message["reasoning_content"] = reasoning_content
    return message


def coerce_message_content_to_text(content: Any) -> str:
    """Convert provider/content payloads into plain text for summaries and estimates."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                item_type = str(item.get("type", ""))
                if item_type == "text":
                    parts.append(str(item.get("text", "")))
                    continue
                if item_type == "image_url":
                    parts.append("[image]")
                    continue
            parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content)


def estimate_content_chars(content: Any) -> int:
    """Estimate character length for heterogeneous content payloads."""
    if content is None:
        return 0
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(estimate_content_chars(item) for item in content)
    if isinstance(content, dict):
        if "text" in content and isinstance(content["text"], str):
            return len(content["text"])
        return sum(estimate_content_chars(value) for value in content.values())
    return len(str(content))


def trim_payload_text(text: str, max_chars: int | None) -> str:
    """Trim text for compact summaries while keeping deterministic formatting."""
    if max_chars is None or max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars] + _TRUNCATION_SUFFIX


def render_message_payload_summary(
    message: dict[str, Any],
    *,
    max_content_chars: int | None = None,
    max_reasoning_chars: int | None = None,
    max_tool_args_chars: int | None = None,
) -> str:
    """Render a compact textual summary of one message payload."""
    role = str(message.get("role", ""))
    lines: list[str] = []

    if role == "tool":
        tool_name = str(message.get("name", "")).strip()
        if tool_name:
            lines.append(f"tool_result: {tool_name}")

    content = trim_payload_text(
        coerce_message_content_to_text(message.get("content", "")),
        max_content_chars,
    )
    if content:
        lines.append(content)

    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls:
        for index, tool_call in enumerate(tool_calls[:_MAX_TOOL_CALLS_TO_RENDER], start=1):
            function = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
            name = str(function.get("name", "")).strip() or f"tool_{index}"
            arguments = trim_payload_text(
                coerce_message_content_to_text(function.get("arguments", "")),
                max_tool_args_chars,
            )
            if arguments:
                lines.append(f"tool_call: {name}({arguments})")
            else:
                lines.append(f"tool_call: {name}()")
        extra_count = len(tool_calls) - _MAX_TOOL_CALLS_TO_RENDER
        if extra_count > 0:
            lines.append(f"tool_call: ... {extra_count} more")

    reasoning = trim_payload_text(
        coerce_message_content_to_text(message.get("reasoning_content", "")),
        max_reasoning_chars,
    )
    if reasoning:
        lines.append(f"reasoning: {reasoning}")

    return "\n".join(line for line in lines if line).strip()
