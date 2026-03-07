"""Shared helpers for token-based context budgeting."""

from __future__ import annotations

import json
from typing import Any


def rough_tokens_from_chars(chars: int) -> int:
    """Return rough token count using ceil(chars / 4)."""
    return (max(chars, 0) + 3) // 4


def estimate_text_tokens(text: str, model: str | None = None) -> int:
    """Estimate token count for plain text."""
    if not text:
        return 0

    if model:
        try:
            import litellm

            return int(
                litellm.token_counter(model=model, messages=[{"role": "user", "content": text}])
            )
        except Exception:
            pass

    return rough_tokens_from_chars(len(text))


def estimate_content_tokens(content: Any, model: str | None = None) -> int:
    """Estimate token count for heterogeneous message content."""
    if content is None:
        return 0
    if isinstance(content, str):
        return estimate_text_tokens(content, model=model)
    if isinstance(content, (list, dict)):
        return estimate_text_tokens(json.dumps(content, ensure_ascii=False), model=model)
    return estimate_text_tokens(str(content), model=model)


def trim_text_to_token_budget(
    text: str,
    max_tokens: int,
    *,
    model: str | None = None,
    suffix: str = "",
    collapse_newlines: bool = False,
) -> str:
    """Trim text to fit a token budget with optional suffix."""
    if max_tokens <= 0:
        return text

    base = text.replace("\n", " ") if collapse_newlines else text
    if estimate_text_tokens(base, model=model) <= max_tokens:
        return base

    suffix_tokens = estimate_text_tokens(suffix, model=model) if suffix else 0
    if suffix and suffix_tokens >= max_tokens:
        return _fit_prefix(base, max_tokens, model=model).rstrip()

    prefix_budget = max_tokens - suffix_tokens
    prefix = _fit_prefix(base, prefix_budget, model=model).rstrip()
    return f"{prefix}{suffix}" if suffix else prefix


def _fit_prefix(text: str, budget_tokens: int, *, model: str | None = None) -> str:
    """Binary search the longest prefix that fits the given token budget."""
    if budget_tokens <= 0 or not text:
        return ""

    low = 0
    high = len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if estimate_text_tokens(text[:mid], model=model) <= budget_tokens:
            low = mid
        else:
            high = mid - 1
    return text[:low]
