"""Helpers for appending assistant/tool payloads to a message list."""

from __future__ import annotations

from typing import Any

from hal.core.message_payloads import build_assistant_message_payload


def add_tool_result(
    messages: list[dict[str, Any]],
    tool_call_id: str,
    tool_name: str,
    result: str,
) -> list[dict[str, Any]]:
    """Append one tool result message and return the original list."""
    messages.append(
        {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": result,
        }
    )
    return messages


def add_assistant_message(
    messages: list[dict[str, Any]],
    content: str | None,
    tool_calls: list[dict[str, Any]] | None = None,
    reasoning_content: str | None = None,
) -> list[dict[str, Any]]:
    """Append one assistant message payload and return the original list."""
    messages.append(
        build_assistant_message_payload(
            content=content,
            tool_calls=tool_calls,
            reasoning_content=reasoning_content,
        )
    )
    return messages
