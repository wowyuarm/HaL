"""Runtime debrief orchestration facade."""

from __future__ import annotations

from typing import Any

from .debrief_flow import generate_episode_markdown as _generate_episode_markdown
from .debrief_flow import resolve_debrief_thread_order as _resolve_debrief_thread_order
from .debrief_flow import run_session_debrief as _run_session_debrief


async def run_session_debrief(engine: Any, session_key: str) -> None:
    """Run session debrief using the current engine runtime implementation."""
    await _run_session_debrief(engine, session_key)


async def generate_episode_markdown(
    engine: Any,
    *,
    session_id: str,
    thread_slug: str,
    state_content: str,
    rendered_events: str,
) -> str:
    """Generate one debrief episode markdown using runtime orchestration."""
    return await _generate_episode_markdown(
        engine,
        session_id=session_id,
        thread_slug=thread_slug,
        state_content=state_content,
        rendered_events=rendered_events,
    )


def resolve_debrief_thread_order(
    *,
    context_registry: object,
    touched_threads: set[str],
) -> list[str]:
    """Resolve debrief thread order using runtime policy helpers."""
    return _resolve_debrief_thread_order(
        context_registry=context_registry,
        touched_threads=touched_threads,
    )


__all__ = [
    "generate_episode_markdown",
    "resolve_debrief_thread_order",
    "run_session_debrief",
]
