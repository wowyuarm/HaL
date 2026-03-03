"""Message shaping helpers for LiteLLM chat requests."""

from __future__ import annotations

from typing import Any

ALLOWED_KEYS_BY_ROLE: dict[str, set[str]] = {
    "system": {"role", "content"},
    "user": {"role", "content"},
    "assistant": {"role", "content", "tool_calls"},
    "tool": {"role", "tool_call_id", "name", "content"},
}

REASONING_MODEL_KEYWORDS: tuple[str, ...] = ("moonshot/", "kimi")
THINKING_ENABLED_VALUES: set[str] = {"enabled", "enable", "on", "true", "1"}


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
