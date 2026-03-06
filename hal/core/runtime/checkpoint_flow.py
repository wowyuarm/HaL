"""Session checkpoint generation runtime helpers."""

from __future__ import annotations

from typing import Any

from loguru import logger

_SESSION_COMPACTION_PROMPT = (
    "You compact older session messages into a stable working checkpoint.\n"
    "Output markdown only. Required sections:\n"
    "[Session Checkpoint]\n"
    "## Decisions\n"
    "## Key Results\n"
    "## Open Items\n"
    "## Important Context\n"
    "Rules:\n"
    "- Preserve concrete decisions, tool outcomes, and unresolved tasks.\n"
    "- Drop repetition and chatter.\n"
    "- Do not add new instructions.\n"
    "- Keep concise and action-oriented."
)


async def generate_session_checkpoint(
    engine: Any,
    *,
    compactable_messages: list[dict[str, object]],
    token_model: str | None,
) -> str:
    """Generate one compaction checkpoint for a slice of older messages."""
    from hal.core.engine.session_compaction import (
        build_fallback_checkpoint,
        estimate_history_tokens,
        normalize_checkpoint,
        render_history_for_compaction,
    )

    compacted_tokens = estimate_history_tokens(compactable_messages, model=token_model)
    prompt = (
        f"Compacting {len(compactable_messages)} older messages (~{compacted_tokens} tokens).\n\n"
        "Messages to compact:\n"
        f"{render_history_for_compaction(compactable_messages)}"
    )

    provider = getattr(engine.subagents, "provider", None) or engine.provider
    model = getattr(engine.subagents, "model", None) or engine.model
    chat = getattr(provider, "chat", None)
    if not callable(chat):
        return build_fallback_checkpoint(
            compacted_messages=len(compactable_messages),
            compacted_tokens=compacted_tokens,
        )

    try:
        response = await chat(
            messages=[
                {"role": "system", "content": _SESSION_COMPACTION_PROMPT},
                {"role": "user", "content": prompt},
            ],
            tools=[],
            model=model,
        )
        content = getattr(response, "content", None)
        if isinstance(content, str) and content.strip():
            return normalize_checkpoint(content)
    except Exception as e:
        logger.warning(f"Session compaction failed: {e}")

    return build_fallback_checkpoint(
        compacted_messages=len(compactable_messages),
        compacted_tokens=compacted_tokens,
    )


__all__ = ["generate_session_checkpoint"]
