"""Message construction helpers for context working sets."""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any

from hal.domain.message_payloads import build_assistant_message_payload


def build_user_message_content(
    text: str,
    media: list[str] | None,
    dynamic_context: str | None = None,
) -> str | list[dict[str, Any]]:
    """Build user message content with optional dynamic context and images."""
    if dynamic_context:
        text = f"{dynamic_context}\n\n{text}"

    if not media:
        return text

    images: list[dict[str, Any]] = []
    for path in media:
        image_payload = _load_image_payload(path)
        if image_payload is not None:
            images.append(image_payload)

    if not images:
        return text
    return images + [{"type": "text", "text": text}]


def _load_image_payload(path: str) -> dict[str, Any] | None:
    p = Path(path)
    mime, _ = mimetypes.guess_type(path)
    if not p.is_file() or not mime or not mime.startswith("image/"):
        return None
    b64 = base64.b64encode(p.read_bytes()).decode()
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime};base64,{b64}"},
    }


# ---------------------------------------------------------------------------
# Assistant / tool-result append helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Working-set sequence assembly
# ---------------------------------------------------------------------------


def build_system_message(system_prompt: str) -> dict[str, object]:
    """Wrap rendered system prompt text into one system-role message."""
    return {"role": "system", "content": system_prompt}


def assemble_message_sequence(
    *,
    system_message: dict[str, object],
    history: list[dict[str, object]] | None = None,
    user_message: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    """Assemble a working-set message sequence from stable and optional layers."""
    messages: list[dict[str, object]] = [system_message]
    if history:
        messages.extend(history)
    if user_message is not None:
        messages.append(user_message)
    return messages


def copy_replay_history(
    messages: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Copy replayable messages while dropping the leading system prompt."""
    return [dict(item) for item in messages[1:]]
