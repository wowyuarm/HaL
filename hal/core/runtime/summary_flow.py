"""Runtime summary-trigger orchestration facade."""

from __future__ import annotations

import asyncio
from typing import Any

from .summary_flow_impl import resolve_summary_model_id as _resolve_summary_model_id
from .summary_flow_impl import trigger_summary_task as _trigger_summary_task


def resolve_summary_model_id(engine: Any) -> str:
    """Resolve summary model id for the current runtime configuration."""
    return _resolve_summary_model_id(engine)


def trigger_summary_task(
    engine: Any,
    *,
    meta: Any,
    final_content: str,
    channel: str,
    chat_id: str,
) -> asyncio.Task | None:
    """Trigger summary task when summary conditions are met."""
    return _trigger_summary_task(
        engine,
        meta=meta,
        final_content=final_content,
        channel=channel,
        chat_id=chat_id,
    )


__all__ = ["resolve_summary_model_id", "trigger_summary_task"]
