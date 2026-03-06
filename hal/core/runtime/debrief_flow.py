"""Runtime session debrief orchestration implementation."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

_EPISODE_SYSTEM_PROMPT = (
    "You convert one session event stream into a compact thread episode.\n"
    "Return markdown only with sections:\n"
    "# <date>: <title>\n"
    "Threads: [<thread>]\n"
    "Primary: <thread>\n"
    "Session: <session_id>\n"
    "## What Happened\n"
    "## Decisions\n"
    "## Status\n"
    "## Artifacts\n"
    "## Open\n"
    "## Source Events\n"
    "Keep it concise and action-oriented."
)


async def run_session_debrief(engine: Any, session_key: str) -> None:
    """Generate episodes and patch state files for one closed session."""
    state = engine._session_states.get(session_key)
    if state is None:
        return
    session_id = state.session_id
    from hal.core.engine.debrief import format_session_events_for_prompt

    events = engine.memory.event_log.read_session(session_id)
    rendered_events = format_session_events_for_prompt(events)
    updated_threads: list[str] = []
    written_episodes: list[Path] = []

    for thread_slug in resolve_debrief_thread_order(
        context_registry=engine.context_registry,
        touched_threads=state.touched_threads,
    ):
        state_content = engine.thread_repository.read_state(thread_slug)
        if state_content is None:
            continue

        episode_markdown = await generate_episode_markdown(
            engine,
            session_id=session_id,
            thread_slug=thread_slug,
            state_content=state_content,
            rendered_events=rendered_events,
        )
        write_result = engine.thread_repository.record_debrief_episode(
            thread_slug=thread_slug,
            session_id=session_id,
            episode_markdown=episode_markdown,
            now=datetime.now(),
            state_content=state_content,
        )
        if write_result is None:
            continue
        written_episodes.append(write_result.episode_path)
        updated_threads.append(thread_slug)

    indexed_chunks = 0
    if written_episodes and engine._memory_search is not None:
        try:
            indexed_chunks = await engine._memory_search.index_paths(written_episodes)
        except Exception as e:
            logger.warning(f"Episode indexing after debrief failed: {e}")

    engine.memory.record_event(
        session_id=session_id,
        event_type="session_debrief_complete",
        channel=state.channel,
        chat_id=state.chat_id,
        payload={
            "threads": updated_threads,
            "episode_count": len(written_episodes),
            "indexed_chunks": indexed_chunks,
        },
    )


async def generate_episode_markdown(
    engine: Any,
    *,
    session_id: str,
    thread_slug: str,
    state_content: str,
    rendered_events: str,
) -> str:
    """Generate thread episode markdown via worker/main model with fallback."""
    prompt = (
        f"Thread: {thread_slug}\nSession: {session_id}\n\n"
        f"Current STATE.md:\n{state_content[:6000]}\n\n"
        f"Session events:\n{rendered_events[:12000]}"
    )
    try:
        response = await engine.provider.chat(
            messages=[
                {"role": "system", "content": _EPISODE_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            tools=[],
            model=engine.model,
        )
        if response.content and isinstance(response.content, str):
            return response.content.strip()
    except Exception as e:
        logger.warning(f"Session debrief generation failed for {thread_slug}: {e}")

    return _build_fallback_episode_markdown(session_id=session_id, thread_slug=thread_slug)


def _build_fallback_episode_markdown(*, session_id: str, thread_slug: str) -> str:
    """Build deterministic fallback episode markdown when generation fails."""
    date_prefix = datetime.now().strftime("%Y-%m-%d")
    return (
        f"# {date_prefix}: Session update for {thread_slug}\n\n"
        f"Threads: [{thread_slug}]\n"
        f"Primary: {thread_slug}\n"
        f"Session: {session_id}\n\n"
        "## What Happened\n"
        "- Session debrief fallback summary generated.\n\n"
        "## Decisions\n"
        "- none\n\n"
        "## Status\n"
        "- unchanged\n\n"
        "## Artifacts\n"
        "- none\n\n"
        "## Open\n"
        "- [ ] Review this fallback and refine manually if needed.\n\n"
        "## Source Events\n"
        f"- {session_id}\n"
    )


def resolve_debrief_thread_order(
    *,
    context_registry: object,
    touched_threads: set[str],
) -> list[str]:
    """Resolve debrief thread order using registry priority and one-hop relations."""
    if not touched_threads:
        return []
    slugs = _expand_related_threads(context_registry, touched_threads)
    priority_map = _build_thread_priority_map(context_registry)
    return sorted(slugs, key=lambda slug: (-priority_map.get(slug, 0), slug))


def _expand_related_threads(context_registry: object, touched_threads: set[str]) -> set[str]:
    expand = getattr(context_registry, "expand_related_thread_slugs", None)
    if not callable(expand):
        return set(touched_threads)
    try:
        expanded = expand(set(touched_threads))
    except Exception:
        return set(touched_threads)
    if not isinstance(expanded, set):
        return set(touched_threads)
    normalized = {str(slug).strip() for slug in expanded if str(slug).strip()}
    return normalized or set(touched_threads)


def _build_thread_priority_map(context_registry: object) -> dict[str, int]:
    snapshot_fn = getattr(context_registry, "thread_snapshot", None)
    if not callable(snapshot_fn):
        return {}
    try:
        snapshot = snapshot_fn()
    except Exception:
        return {}
    if not isinstance(snapshot, list):
        return {}
    priorities: dict[str, int] = {}
    for item in snapshot:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("slug", "")).strip()
        if not slug:
            continue
        priority = item.get("priority", 0)
        try:
            priorities[slug] = int(priority)
        except (TypeError, ValueError):
            priorities[slug] = 0
    return priorities


__all__ = ["generate_episode_markdown", "resolve_debrief_thread_order", "run_session_debrief"]
