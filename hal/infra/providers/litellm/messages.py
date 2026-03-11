"""Message shaping helpers for LiteLLM chat requests."""

from __future__ import annotations

import copy
import json
from typing import Any

ALLOWED_KEYS_BY_ROLE: dict[str, set[str]] = {
    "system": {"role", "content"},
    "user": {"role", "content"},
    "assistant": {"role", "content", "tool_calls"},
    "tool": {"role", "tool_call_id", "name", "content"},
}

REASONING_MODEL_KEYWORDS: tuple[str, ...] = ("moonshot/", "kimi")
THINKING_ENABLED_VALUES: set[str] = {"enabled", "enable", "on", "true", "1"}
REQUEST_SIZE_TRUNCATION_SUFFIX = "\n...[truncated to fit request size]"
REQUEST_SIZE_TEXT_PLACEHOLDER = "[earlier message omitted to fit request size]"
REQUEST_SIZE_TOOL_PLACEHOLDER = "[tool result omitted to fit request size]"
REQUEST_SIZE_IMAGE_PLACEHOLDER = "[prior image omitted to fit request size]"
_TRIM_STEPS_BY_ROLE: dict[str, tuple[int | None, ...]] = {
    "tool": (4_000, 1_200, 400, None),
    "assistant": (8_000, 2_000, 600, None),
    "user": (8_000, 2_000, 600, None),
    "system": (16_000, 8_000, 2_000),
}


def is_thinking_enabled(value: Any) -> bool:
    """Return True when a provider-level thinking flag is enabled."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in THINKING_ENABLED_VALUES
    if isinstance(value, dict):
        if not value:
            return False
        thinking_type = value.get("type")
        if thinking_type is None:
            return True
        if isinstance(thinking_type, str):
            return thinking_type.strip().lower() in THINKING_ENABLED_VALUES
        return bool(thinking_type)
    return bool(value)


def should_preserve_reasoning_content(
    model: str,
    gateway_name: str | None,
    request_params: dict[str, Any] | None,
) -> bool:
    """Keep reasoning content only for thinking paths that validate tool-call replay."""
    model_lower = model.lower()
    if any(keyword in model_lower for keyword in REASONING_MODEL_KEYWORDS):
        return True
    if gateway_name == "anyrouter":
        return True
    params = request_params or {}
    return is_thinking_enabled(params.get("thinking"))


def sanitize_messages(
    messages: list[dict[str, Any]],
    preserve_reasoning_content: bool = False,
) -> list[dict[str, Any]]:
    """Sanitize messages before LLM dispatch."""
    sanitized: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role", "user")
        allowed = ALLOWED_KEYS_BY_ROLE.get(role)

        if allowed is None:
            # Unknown role — pass through as-is (future-proofing)
            sanitized.append(msg)
            continue

        allowed_keys = set(allowed)
        if role == "assistant" and preserve_reasoning_content:
            allowed_keys.add("reasoning_content")

        cleaned: dict[str, Any] = {k: v for k, v in msg.items() if k in allowed_keys}

        # Ensure content is never None (providers may reject null content)
        if cleaned.get("content") is None:
            cleaned["content"] = ""

        # Some thinking providers require reasoning_content to exist on
        # assistant tool-call messages in replayed conversation context.
        if (
            role == "assistant"
            and preserve_reasoning_content
            and cleaned.get("tool_calls")
            and "reasoning_content" not in cleaned
        ):
            cleaned["reasoning_content"] = ""

        sanitized.append(cleaned)

    return sanitized


def estimate_request_payload_bytes(payload: dict[str, Any]) -> int:
    """Estimate serialized request size in UTF-8 bytes."""
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def trim_messages_to_request_budget(
    messages: list[dict[str, Any]],
    *,
    base_payload: dict[str, Any],
    max_bytes: int,
) -> tuple[list[dict[str, Any]], bool]:
    """Shrink oversized message payloads until the serialized request fits the byte budget."""
    if max_bytes <= 0:
        return messages, False

    payload = dict(base_payload)
    payload["messages"] = messages
    if estimate_request_payload_bytes(payload) <= max_bytes:
        return messages, False

    trimmed = copy.deepcopy(messages)
    changed = False
    latest_index = len(trimmed) - 1

    for index, message in enumerate(trimmed):
        if "reasoning_content" in message:
            message.pop("reasoning_content", None)
            changed = True
            payload["messages"] = trimmed
            if estimate_request_payload_bytes(payload) <= max_bytes:
                return trimmed, changed

    for pass_latest in (False, True):
        for index, message in enumerate(trimmed):
            if not pass_latest and index == latest_index:
                continue
            if pass_latest and index != latest_index:
                continue
            changed_this_message = _trim_message_progressively(message)
            if not changed_this_message:
                continue
            changed = True
            payload["messages"] = trimmed
            if estimate_request_payload_bytes(payload) <= max_bytes:
                return trimmed, changed

    return trimmed, changed


def _trim_message_progressively(message: dict[str, Any]) -> bool:
    """Apply staged shrinking to one message until no more reductions are possible."""
    role = str(message.get("role", "user"))
    changed = False

    content = message.get("content")
    if isinstance(content, list):
        collapsed = _collapse_multimodal_content(content)
        if collapsed != content:
            message["content"] = collapsed
            content = collapsed
            changed = True

    if not isinstance(content, str):
        return changed

    steps = _TRIM_STEPS_BY_ROLE.get(role, _TRIM_STEPS_BY_ROLE["user"])
    placeholder = REQUEST_SIZE_TOOL_PLACEHOLDER if role == "tool" else REQUEST_SIZE_TEXT_PLACEHOLDER
    for limit in steps:
        updated = _apply_text_trim_step(content, limit=limit, placeholder=placeholder)
        if updated == content:
            continue
        message["content"] = updated
        content = updated
        changed = True

    return changed


def _collapse_multimodal_content(content: list[Any]) -> str | list[Any]:
    """Reduce multimodal history entries to a compact textual placeholder."""
    parts: list[str] = []
    saw_image = False

    for item in content:
        if not isinstance(item, dict):
            if item:
                parts.append(str(item))
            continue
        item_type = str(item.get("type", ""))
        if item_type == "text":
            text = item.get("text")
            if text:
                parts.append(str(text))
            continue
        if item_type == "image_url":
            saw_image = True

    if saw_image:
        parts.insert(0, REQUEST_SIZE_IMAGE_PLACEHOLDER)

    if not parts:
        return [{"type": "text", "text": REQUEST_SIZE_TEXT_PLACEHOLDER}]
    return "\n".join(part for part in parts if part)


def _apply_text_trim_step(text: str, *, limit: int | None, placeholder: str) -> str:
    """Apply one staged trim transformation to a text payload."""
    if limit is None:
        return placeholder
    if len(text) <= limit:
        return text
    suffix = REQUEST_SIZE_TRUNCATION_SUFFIX
    budget = max(limit - len(suffix), 0)
    prefix = text[:budget].rstrip() if budget > 0 else ""
    return f"{prefix}{suffix}" if prefix else suffix.lstrip()
