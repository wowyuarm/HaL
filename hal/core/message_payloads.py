"""Shared helpers for building LLM message payloads."""

from __future__ import annotations

from typing import Any


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

