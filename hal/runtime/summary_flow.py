"""Summary-trigger orchestration helpers."""

from __future__ import annotations

import asyncio
from typing import Any

from hal.runtime.summary import generate_summary


def resolve_summary_model_id(engine: Any) -> str:
    """Resolve the model to use for summary generation."""
    return engine.model if engine._summary_model == "default" else engine._summary_model


def trigger_summary_task(
    engine: Any,
    *,
    meta: object,
    final_content: str,
    channel: str,
    chat_id: str,
) -> asyncio.Task | None:
    """Create an async summary task when loop metadata qualifies."""
    if not bool(getattr(meta, "needs_summary", False)):
        return None
    return asyncio.create_task(
        generate_summary(
            meta=meta,
            final_content=final_content,
            channel=channel,
            chat_id=chat_id,
            provider=engine._summary_provider or engine.provider,
            model=resolve_summary_model_id(engine),
            memory=engine.memory,
        )
    )


__all__ = ["resolve_summary_model_id", "trigger_summary_task"]
