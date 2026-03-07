"""Tests for token budget helpers."""

from __future__ import annotations

from hal.context.token_budget import (
    estimate_content_tokens,
    estimate_text_tokens,
    rough_tokens_from_chars,
    trim_text_to_token_budget,
)


def test_rough_tokens_from_chars_uses_ceil_division() -> None:
    assert rough_tokens_from_chars(0) == 0
    assert rough_tokens_from_chars(1) == 1
    assert rough_tokens_from_chars(4) == 1
    assert rough_tokens_from_chars(5) == 2


def test_trim_text_to_token_budget_keeps_text_when_within_budget() -> None:
    text = "hello world"
    out = trim_text_to_token_budget(text, max_tokens=10)
    assert out == text


def test_trim_text_to_token_budget_truncates_and_keeps_suffix() -> None:
    text = "A" * 400
    out = trim_text_to_token_budget(text, max_tokens=20, suffix=" [...]")
    assert out.endswith("[...]")
    assert len(out) < len(text)
    assert estimate_text_tokens(out) <= 20


def test_trim_text_to_token_budget_handles_oversized_suffix_budget() -> None:
    text = "B" * 200
    out = trim_text_to_token_budget(text, max_tokens=2, suffix=" [very long suffix]")
    assert estimate_text_tokens(out) <= 2


def test_trim_text_to_token_budget_can_collapse_newlines() -> None:
    text = "line1\nline2\nline3\nline4"
    out = trim_text_to_token_budget(text, max_tokens=3, collapse_newlines=True)
    assert "\n" not in out


def test_estimate_content_tokens_supports_structured_payload() -> None:
    payload = [
        {"type": "text", "text": "hello"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
    ]
    tokens = estimate_content_tokens(payload)
    assert isinstance(tokens, int)
    assert tokens > 0
