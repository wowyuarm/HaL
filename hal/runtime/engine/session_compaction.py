"""Helpers for in-session history compaction."""

from __future__ import annotations

import re
from typing import Any

from hal.context.token_budget import estimate_content_tokens
from hal.domain.message_payloads import render_message_payload_summary

_SESSION_CHECKPOINT_HEADER = "[Session Checkpoint]"
_MAX_RENDER_CHAR_PER_MESSAGE = 2400
_MAX_RENDER_TOTAL_CHARS = 60000
_MAX_REASONING_CHAR_PER_MESSAGE = 1200
_MAX_TOOL_ARGS_CHAR_PER_MESSAGE = 600

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
        total += estimate_content_tokens(rendered, model=model) + 4
    return total


def split_history_for_compaction(
    history: list[dict[str, Any]],
    *,
    keep_recent_user_turns: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split history into (older_to_compact, recent_tail_to_keep)."""
    if keep_recent_user_turns <= 0:
        return list(history), []

    user_indexes = [i for i, msg in enumerate(history) if msg.get("role") == "user"]
    if len(user_indexes) <= keep_recent_user_turns:
        return [], list(history)

    cut = user_indexes[-keep_recent_user_turns]
    return list(history[:cut]), list(history[cut:])


def render_history_for_compaction(messages: list[dict[str, Any]]) -> str:
    """Render history slice into compact textual form for worker-model compaction."""
    parts: list[str] = []
    total_chars = 0

    for idx, message in enumerate(messages, 1):
        role = str(message.get("role", ""))
        rendered = render_message_payload_summary(
            message,
            max_content_chars=_MAX_RENDER_CHAR_PER_MESSAGE,
            max_reasoning_chars=_MAX_REASONING_CHAR_PER_MESSAGE,
            max_tool_args_chars=_MAX_TOOL_ARGS_CHAR_PER_MESSAGE,
        )
        block = f"[{idx}] {role}"
        if rendered:
            block += f"\n{rendered}"
        total_chars += len(block)
        if total_chars > _MAX_RENDER_TOTAL_CHARS:
            parts.append("[...earlier compactable messages truncated...]")
            break
        parts.append(block)

    return "\n\n".join(parts)


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
    "split_history_for_compaction",
]
