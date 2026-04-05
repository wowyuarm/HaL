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
    *,
    attachments: list[dict[str, object]] | None = None,
) -> str | list[dict[str, Any]]:
    """Build user message content with optional dynamic context and images."""
    image_parts: list[dict[str, Any]] = []
    attachment_texts: list[str] = []

    for attachment in attachments or []:
        for part in _attachment_prompt_parts(attachment):
            if part.get("type") == "image_url":
                image_parts.append(part)
            elif part.get("type") == "text":
                attachment_text = str(part.get("text", "")).strip()
                if attachment_text:
                    attachment_texts.append(attachment_text)

    for path in media or []:
        image_payload = _load_image_payload(path)
        if image_payload is not None:
            image_parts.append(image_payload)

    text_segments = [segment for segment in [dynamic_context, *attachment_texts, text] if segment]
    combined_text = "\n\n".join(text_segments)

    if not image_parts:
        return combined_text
    if combined_text:
        return image_parts + [{"type": "text", "text": combined_text}]
    return image_parts


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


def _attachment_prompt_parts(attachment: dict[str, object]) -> list[dict[str, Any]]:
    name = str(attachment.get("name", "")).strip() or "attachment"
    content_type = str(attachment.get("contentType", "")).strip()
    path = str(attachment.get("path", "")).strip()
    parts = attachment.get("content")
    if not isinstance(parts, list):
        return []

    prompt_parts: list[dict[str, Any]] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        part_type = str(part.get("type", "")).strip()
        if part_type == "image":
            image = str(part.get("image", "")).strip()
            if image:
                prompt_parts.append(
                    {
                        "type": "text",
                        "text": _attachment_label(name, content_type or "image", path, kind="image"),
                    }
                )
                prompt_parts.append({"type": "image_url", "image_url": {"url": image}})
            continue
        if part_type == "text":
            text = str(part.get("text", ""))
            if text.strip():
                label = _attachment_label(name, content_type or "text/plain", path, kind="text")
                prompt_parts.append({"type": "text", "text": f"{label}\n{text}"})
            continue
        if part_type == "file":
            mime_type = (
                str(part.get("mimeType", "")).strip() or content_type or "application/octet-stream"
            )
            filename = str(part.get("filename", "")).strip() or name
            prompt_parts.append(
                {"type": "text", "text": _attachment_label(filename, mime_type, path, kind="file")}
            )

    return prompt_parts


def _attachment_label(name: str, mime_type: str, path: str, *, kind: str) -> str:
    if path:
        return f"[Attached {kind}: {name} ({mime_type}, path: {path})]"
    return f"[Attached {kind}: {name} ({mime_type})]"


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
    reasoning_details: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Append one assistant message payload and return the original list."""
    messages.append(
        build_assistant_message_payload(
            content=content,
            tool_calls=tool_calls,
            reasoning_content=reasoning_content,
            reasoning_details=reasoning_details,
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
