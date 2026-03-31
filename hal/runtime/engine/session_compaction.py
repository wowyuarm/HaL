"""Helpers for in-session history compaction."""

from __future__ import annotations

import re
from typing import Any

from hal.context.token_counter import count_content_tokens
from hal.domain.message_payloads import render_message_payload_summary
from hal.runtime.worker_inputs import build_history_input_lines, render_worker_input_lines

_SESSION_CHECKPOINT_HEADER = "[Session Checkpoint]"
_MAX_RENDER_TOKENS_PER_MESSAGE = 1200
_MAX_RENDER_TOTAL_TOKENS = 12_000

_ANALYSIS_TAG_RE = re.compile(r"<analysis>.*?</analysis>\s*", re.DOTALL)


def estimate_history_tokens(history: list[dict[str, Any]], *, model: str | None = None) -> int:
    """Estimate token usage for session history messages."""
    total = 0
    for message in history:
        rendered = render_message_payload_summary(
            message,
            max_content_chars=None,
            max_reasoning_chars=None,
            max_tool_args_chars=None,
        )
        total += count_content_tokens(rendered, model=model) + 4
    return total


def render_history_for_compaction(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
) -> str:
    """Render history slice into compact textual form for worker-model compaction."""
    rendered = render_worker_input_lines(
        build_history_input_lines(messages),
        model=model,
        max_line_tokens=_MAX_RENDER_TOKENS_PER_MESSAGE,
        max_total_tokens=_MAX_RENDER_TOTAL_TOKENS,
        empty_text="[...earlier compactable messages truncated...]",
        line_suffix="\n...[truncated]",
        total_suffix="\n\n[...earlier compactable messages truncated...]",
    )
    return rendered or "[...earlier compactable messages truncated...]"


def normalize_checkpoint(content: str) -> str:
    """Normalize model output into a stable checkpoint format.

    Strips <analysis>...</analysis> blocks (used for chain-of-thought during
    compaction) and ensures the checkpoint header is present.
    """
    text = (content or "").strip()
    if not text:
        return _SESSION_CHECKPOINT_HEADER
    # Strip analysis tags — they served as worker-model reasoning scaffolding.
    text = _ANALYSIS_TAG_RE.sub("", text).strip()
    if not text:
        return _SESSION_CHECKPOINT_HEADER
    if _SESSION_CHECKPOINT_HEADER in text:
        return text
    return f"{_SESSION_CHECKPOINT_HEADER}\n\n{text}"


def build_fallback_checkpoint(*, compacted_messages: int, compacted_tokens: int) -> str:
    """Build deterministic fallback checkpoint when model compaction fails."""
    return (
        f"{_SESSION_CHECKPOINT_HEADER}\n\n"
        f"Compacted {compacted_messages} older messages (~{compacted_tokens} tokens).\n"
        "No structured checkpoint could be generated. "
        "Review events log for earlier details if needed.\n"
    )


__all__ = [
    "build_fallback_checkpoint",
    "estimate_history_tokens",
    "normalize_checkpoint",
    "render_history_for_compaction",
]
