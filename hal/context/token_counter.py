"""Shared token counting helpers used by context budgeting and inspection."""

from __future__ import annotations

import json
from typing import Any

from hal.domain.message_payloads import estimate_content_chars

FALLBACK_METHOD = "chars_div_4"
LITELLM_METHOD = "litellm.token_counter"
_CHARS_PER_ROUGH_TOKEN = 4


def rough_tokens_from_chars(chars: int) -> int:
    """Return rough token count using ceil(chars / 4)."""
    return (max(chars, 0) + (_CHARS_PER_ROUGH_TOKEN - 1)) // _CHARS_PER_ROUGH_TOKEN


def count_text_tokens(text: str, *, model: str | None = None) -> int:
    """Estimate token count for plain text."""
    if not text:
        return 0
    return _count_messages_via_litellm(
        [{"role": "user", "content": text}],
        model=model,
        fallback=rough_tokens_from_chars(len(text)),
    )


def count_content_tokens(content: Any, *, model: str | None = None) -> int:
    """Estimate token count for heterogeneous message content."""
    if content is None:
        return 0
    if isinstance(content, str):
        return count_text_tokens(content, model=model)
    if isinstance(content, (list, dict)):
        return count_text_tokens(json.dumps(content, ensure_ascii=False), model=model)
    return count_text_tokens(str(content), model=model)


def count_messages_tokens(messages: list[dict[str, Any]], *, model: str | None = None) -> int:
    """Estimate token count for a list of chat messages."""
    if not messages:
        return 0
    fallback = rough_tokens_from_chars(
        sum(estimate_content_chars(message.get("content", "")) for message in messages)
    )
    return _count_messages_via_litellm(messages, model=model, fallback=fallback)


def count_message_tokens(message: dict[str, Any], *, model: str | None = None) -> int:
    """Estimate token count for one chat message."""
    return count_messages_tokens([message], model=model)


def count_prompt_tokens(
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    model: str | None = None,
) -> dict[str, Any]:
    """Estimate prompt usage for messages with optional tool schemas."""
    msg_chars = sum(estimate_content_chars(message.get("content", "")) for message in messages)
    tools_chars = len(json.dumps(tools, ensure_ascii=False))
    fallback = {
        "method": FALLBACK_METHOD,
        "messages_only": rough_tokens_from_chars(msg_chars),
        "with_tools": rough_tokens_from_chars(msg_chars + tools_chars),
        "tools_only": rough_tokens_from_chars(tools_chars),
        "error": None,
    }
    if not model:
        return fallback

    try:
        import litellm

        messages_only = int(litellm.token_counter(model=model, messages=messages))
        with_tools = int(litellm.token_counter(model=model, messages=messages, tools=tools))
        return {
            "method": LITELLM_METHOD,
            "messages_only": messages_only,
            "with_tools": with_tools,
            "tools_only": max(with_tools - messages_only, 0),
            "error": None,
        }
    except Exception as exc:
        fallback["error"] = str(exc)
        return fallback


def _count_messages_via_litellm(
    messages: list[dict[str, Any]],
    *,
    model: str | None,
    fallback: int,
) -> int:
    """Use LiteLLM token counting when a model is available, else return fallback."""
    if not model:
        return fallback
    try:
        import litellm

        return int(litellm.token_counter(model=model, messages=messages))
    except Exception:
        return fallback


__all__ = [
    "FALLBACK_METHOD",
    "LITELLM_METHOD",
    "count_content_tokens",
    "count_message_tokens",
    "count_messages_tokens",
    "count_prompt_tokens",
    "count_text_tokens",
    "rough_tokens_from_chars",
]
