"""Usage parsing helpers for LiteLLM responses."""

from __future__ import annotations

from typing import Any

_PROMPT_TOKEN_KEYS = ("prompt_tokens", "input_tokens")
_COMPLETION_TOKEN_KEYS = ("completion_tokens", "output_tokens")
_CACHE_CREATION_KEYS = ("cache_creation_input_tokens", "_cache_creation_input_tokens")
_CACHE_READ_KEYS = ("cache_read_input_tokens", "_cache_read_input_tokens")
_TOTAL_TOKENS_KEY = "total_tokens"
_PROMPT_DETAILS_KEY = "prompt_tokens_details"
_PROMPT_CACHED_TOKENS_KEY = "cached_tokens"
_PROMPT_CACHE_MISS_KEY = "prompt_cache_miss_tokens"


def coerce_usage_int(value: Any) -> int | None:
    """Convert usage fields to int while rejecting non-numeric booleans."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def read_usage_field(usage: Any, key: str) -> int | None:
    """Read a usage field from either dict-like or object-like usage payload."""
    if isinstance(usage, dict):
        return coerce_usage_int(usage.get(key))
    return coerce_usage_int(getattr(usage, key, None))


def _read_first_usage_field(usage: Any, keys: tuple[str, ...]) -> int | None:
    """Read the first non-null usage field from a list of aliases."""
    for key in keys:
        value = read_usage_field(usage, key)
        if value is not None:
            return value
    return None


def _read_prompt_cached_tokens(usage: Any) -> int | None:
    """Read cached tokens from prompt_tokens_details when present."""
    prompt_details = (
        usage.get(_PROMPT_DETAILS_KEY)
        if isinstance(usage, dict)
        else getattr(usage, _PROMPT_DETAILS_KEY, None)
    )
    if prompt_details is None:
        return None
    return read_usage_field(prompt_details, _PROMPT_CACHED_TOKENS_KEY)


def _set_usage_field(extracted: dict[str, int], key: str, value: int | None) -> None:
    """Set extracted usage field if value is present."""
    if value is not None:
        extracted[key] = value


def _ensure_total_tokens(extracted: dict[str, int]) -> None:
    """Derive total_tokens when prompt/completion exist but total is missing."""
    if (
        _TOTAL_TOKENS_KEY not in extracted
        and "prompt_tokens" in extracted
        and "completion_tokens" in extracted
    ):
        extracted[_TOTAL_TOKENS_KEY] = extracted["prompt_tokens"] + extracted["completion_tokens"]


def extract_usage(usage: Any) -> dict[str, int]:
    """Normalize provider-specific usage payloads into a common shape."""
    if not usage:
        return {}

    extracted: dict[str, int] = {}
    _set_usage_field(
        extracted,
        "prompt_tokens",
        _read_first_usage_field(usage, _PROMPT_TOKEN_KEYS),
    )
    _set_usage_field(
        extracted,
        "completion_tokens",
        _read_first_usage_field(usage, _COMPLETION_TOKEN_KEYS),
    )
    _set_usage_field(
        extracted,
        _TOTAL_TOKENS_KEY,
        read_usage_field(usage, _TOTAL_TOKENS_KEY),
    )
    _set_usage_field(
        extracted,
        "cache_creation_input_tokens",
        _read_first_usage_field(usage, _CACHE_CREATION_KEYS),
    )

    cache_read = _read_first_usage_field(usage, _CACHE_READ_KEYS)
    if cache_read is None:
        cache_read = _read_prompt_cached_tokens(usage)
    _set_usage_field(extracted, "cache_read_input_tokens", cache_read)
    _set_usage_field(
        extracted,
        _PROMPT_CACHE_MISS_KEY,
        read_usage_field(usage, _PROMPT_CACHE_MISS_KEY),
    )

    _ensure_total_tokens(extracted)

    return extracted
