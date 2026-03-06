"""Runtime checkpoint orchestration facade."""

from __future__ import annotations

from typing import Any

from .checkpoint_flow import generate_session_checkpoint as _generate_session_checkpoint


async def generate_session_checkpoint(
    engine: Any,
    *,
    compactable_messages: list[dict[str, object]],
    token_model: str | None,
) -> str:
    """Generate one session compaction checkpoint via runtime orchestration."""
    return await _generate_session_checkpoint(
        engine,
        compactable_messages=compactable_messages,
        token_model=token_model,
    )


__all__ = ["generate_session_checkpoint"]
