"""Runtime session debrief orchestration implementation."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from hal.workspace.events import EventEntry

# ---------------------------------------------------------------------------
# Debrief confirmation and thread extraction helpers
# ---------------------------------------------------------------------------

_THREAD_STATE_PATH_RE = re.compile(r"(?:^|/)threads/([^/]+)/STATE\.md$")
_CONFIRM_TEXTS = {
    "yes",
    "y",
    "ok",
    "confirm",
    "\u786e\u8ba4",
    "\u7ee7\u7eed",
    "\u5f00\u59cb",
    "\U0001f44d",
    "\u2705",
}
_MAX_EVENT_PREVIEW = 200


def build_debrief_confirmation_message(*, threads: list[str], confirm_timeout_s: float) -> str:
    """Build user-visible confirmation text before starting session debrief."""
    thread_text = ", ".join(threads)
    timeout_m = max(int(confirm_timeout_s // 60), 1)
    return (
        "This session touched threads: "
        f"{thread_text}. I will update episodes/STATE in about {timeout_m} minute(s). "
        "Reply to continue chatting and cancel this debrief, or reply 'confirm' to start now."
    )


def is_debrief_confirm_message(content: str) -> bool:
    """Return True when user message should immediately confirm debrief."""
    normalized = content.strip().lower()
    if not normalized:
        return False
    if normalized.startswith("/debrief"):
        return True
    return normalized in _CONFIRM_TEXTS


def extract_thread_slug_from_value(value: Any) -> str | None:
    """Extract thread slug from arbitrary string value containing threads/.../STATE.md."""
    if not isinstance(value, str):
        return None
    normalized = value.replace("\\", "/")
    match = _THREAD_STATE_PATH_RE.search(normalized)
    if not match:
        return None
    return match.group(1)


def extract_touched_threads(arguments: dict[str, Any]) -> set[str]:
    """Recursively collect thread slugs from tool call arguments."""
    found: set[str] = set()

    def _walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for val in obj.values():
                _walk(val)
            return
        if isinstance(obj, list):
            for val in obj:
                _walk(val)
            return
        slug = extract_thread_slug_from_value(obj)
        if slug:
            found.add(slug)

    _walk(arguments)
    return found


def format_session_events_for_prompt(events: list[EventEntry]) -> str:
    """Render compact event stream for worker-model debrief input."""
    lines: list[str] = []
    for event in events:
        payload = event.payload or {}
        preview = _event_preview(payload)
        lines.append(f"- [{event.ts}] {event.type}: {preview}")
    return "\n".join(lines) if lines else "- (no events)"


def _event_preview(payload: dict[str, Any]) -> str:
    if not payload:
        return "(empty)"
    for key in ("content", "tool", "label", "status"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            text = value.strip().replace("\n", " ")
            if len(text) > _MAX_EVENT_PREVIEW:
                return text[:_MAX_EVENT_PREVIEW] + "..."
            return text
    return str(payload)[:_MAX_EVENT_PREVIEW]


# ---------------------------------------------------------------------------
# Debrief orchestration
# ---------------------------------------------------------------------------

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


__all__ = [
    "build_debrief_confirmation_message",
    "extract_thread_slug_from_value",
    "extract_touched_threads",
    "format_session_events_for_prompt",
    "generate_episode_markdown",
    "is_debrief_confirm_message",
    "resolve_debrief_thread_order",
    "run_session_debrief",
]
