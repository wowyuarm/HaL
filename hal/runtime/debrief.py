"""Runtime session debrief orchestration implementation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from hal.context.token_budget import estimate_text_tokens, trim_text_to_token_budget
from hal.workspace.events import EventEntry

# ---------------------------------------------------------------------------
# Debrief confirmation and thread extraction helpers
# ---------------------------------------------------------------------------

# Inline keyboard callback data and metadata keys
DEBRIEF_CONFIRM_CB = "debrief:confirm"
DEBRIEF_CANCEL_CB = "debrief:cancel"
DEBRIEF_ACTION_KEY = "debrief_action"
DEBRIEF_ACTION_CONFIRM = "confirm"
DEBRIEF_ACTION_CANCEL = "cancel"

_THREAD_STATE_PATH_RE = re.compile(r"(?:^|/)threads/([^/]+)/BRIEF\.md$")
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

# Token-based budget defaults for debrief rendering (overridable via DebriefConfig)
_DEFAULT_MAX_EVENT_TOKENS = 1500
_DEFAULT_MAX_STATE_TOKENS = 8000
_DEFAULT_MAX_PROMPT_TOKENS = 100_000
_TRUNCATION_SUFFIX = "\n...[truncated]"


@dataclass(frozen=True, slots=True)
class DebriefOutput:
    """Structured output from the debrief worker model."""

    episode_markdown: str
    brief_markdown: str | None  # None = keep current brief unchanged


def build_debrief_confirmation_message(*, threads: list[str], confirm_timeout_s: float) -> str:
    """Build user-visible confirmation text before starting session debrief."""
    thread_text = ", ".join(threads)
    timeout_m = max(int(confirm_timeout_s // 60), 1)
    return (
        "This session touched threads: "
        f"{thread_text}. I will update briefs/episodes in about {timeout_m} minute(s). "
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


def is_debrief_action_message(metadata: dict[str, Any]) -> str | None:
    """Return the debrief action from message metadata, or None.

    Used by the engine to detect inline-keyboard callback confirmations
    before falling back to text-based matching.
    """
    action = metadata.get(DEBRIEF_ACTION_KEY)
    if action in (DEBRIEF_ACTION_CONFIRM, DEBRIEF_ACTION_CANCEL):
        return action
    return None


def extract_thread_slug_from_value(value: Any) -> str | None:
    """Extract thread slug from arbitrary string value containing threads/.../BRIEF.md."""
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


def format_session_events_for_prompt(
    events: list[EventEntry],
    *,
    model: str | None = None,
    max_tokens: int = _DEFAULT_MAX_PROMPT_TOKENS,
    max_event_tokens: int = _DEFAULT_MAX_EVENT_TOKENS,
) -> str:
    """Render compact event stream for worker-model debrief input.

    Each event is individually capped at *max_event_tokens*. The full
    rendered output is then trimmed to *max_tokens* as a safety net.
    """
    lines: list[str] = []
    for event in events:
        payload = event.payload or {}
        preview = _event_preview(payload, model=model, max_event_tokens=max_event_tokens)
        lines.append(f"- [{event.ts}] {event.type}: {preview}")
    rendered = "\n".join(lines) if lines else "- (no events)"
    return trim_text_to_token_budget(rendered, max_tokens, model=model, suffix=_TRUNCATION_SUFFIX)


def _event_preview(
    payload: dict[str, Any],
    *,
    model: str | None = None,
    max_event_tokens: int = _DEFAULT_MAX_EVENT_TOKENS,
) -> str:
    """Extract a concise preview from one event payload, token-capped."""
    if not payload:
        return "(empty)"
    for key in ("content", "tool", "label", "status"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            text = value.strip().replace("\n", " ")
            return _cap_text(text, model=model, max_event_tokens=max_event_tokens)
    fallback = str(payload)
    return _cap_text(fallback, model=model, max_event_tokens=max_event_tokens)


def _cap_text(
    text: str,
    *,
    model: str | None = None,
    max_event_tokens: int = _DEFAULT_MAX_EVENT_TOKENS,
) -> str:
    """Trim text to max_event_tokens if it exceeds the budget."""
    if estimate_text_tokens(text, model=model) <= max_event_tokens:
        return text
    return trim_text_to_token_budget(text, max_event_tokens, model=model, suffix="...[truncated]")


# ---------------------------------------------------------------------------
# Debrief orchestration
# ---------------------------------------------------------------------------

_DEBRIEF_SYSTEM_PROMPT = (
    "You maintain collaboration briefs for an ongoing thread. "
    "Each session, you receive the current brief and the session's event stream. "
    "You produce two outputs:\n\n"
    "1. An **episode** — immutable record of this session's contribution. "
    "Start with a markdown heading (# date: title), then free-form content: "
    "what happened, decisions made, outcomes. Concise and factual.\n\n"
    "2. An **updated brief** — replaces the current brief entirely. "
    "This is what a collaborator reads at the start of the next session. "
    "It should answer: Where do things stand? What's been decided? "
    "What needs attention? What's the recent trajectory?\n\n"
    "The brief is a living document, not a log. Remove outdated information. "
    "Update status. Evolve its structure as the thread develops. "
    "Different threads warrant different structures — a technical project needs "
    "architecture decisions and blockers; a learning journey needs insights "
    "and open questions; daily coordination needs action items and reminders.\n\n"
    "If the session didn't meaningfully advance this thread, output a minimal "
    "episode and return the brief unchanged.\n\n"
    "Format your response exactly as:\n"
    "---EPISODE---\n"
    "[episode markdown]\n"
    "---BRIEF---\n"
    "[complete updated brief markdown]"
)

_EPISODE_MARKER = "---EPISODE---"
_BRIEF_MARKER = "---BRIEF---"


def _parse_debrief_response(raw: str) -> DebriefOutput:
    """Split worker response into episode + brief. Fallback: entire output as episode."""
    ep_idx = raw.find(_EPISODE_MARKER)
    br_idx = raw.find(_BRIEF_MARKER)
    if ep_idx < 0 or br_idx < 0 or br_idx <= ep_idx:
        return DebriefOutput(episode_markdown=raw.strip(), brief_markdown=None)
    episode = raw[ep_idx + len(_EPISODE_MARKER) : br_idx].strip()
    brief = raw[br_idx + len(_BRIEF_MARKER) :].strip()
    return DebriefOutput(
        episode_markdown=episode or raw.strip(),
        brief_markdown=brief or None,
    )


async def run_session_debrief(engine: Any, session_key: str) -> None:
    """Generate episodes and update briefs for one closed session."""
    state = engine._session_states.get(session_key)
    if state is None:
        return
    session_id = state.session_id

    worker_model = engine._worker_model
    worker_provider = engine._worker_provider
    debrief_cfg = engine._engine_config.debrief

    events = engine.memory.event_log.read_session(session_id)
    rendered_events = format_session_events_for_prompt(
        events,
        model=worker_model,
        max_tokens=debrief_cfg.max_prompt_tokens,
        max_event_tokens=debrief_cfg.max_event_tokens,
    )
    updated_threads: list[str] = []
    written_episodes: list[Path] = []

    # Build thread metadata lookup for name/scope.
    thread_meta: dict[str, dict[str, str]] = {}
    try:
        for item in engine.context_registry.thread_snapshot():
            slug = str(item.get("slug", ""))
            if slug:
                thread_meta[slug] = {
                    "name": str(item.get("name", slug)),
                    "scope": str(item.get("scope", "")),
                }
    except Exception:
        pass

    for thread_slug in resolve_debrief_thread_order(
        context_registry=engine.context_registry,
        touched_threads=state.touched_threads,
    ):
        brief_content = engine.thread_repository.read_state(thread_slug)
        if brief_content is None:
            continue

        meta = thread_meta.get(thread_slug, {})
        output = await generate_debrief_output(
            worker_provider,
            worker_model=worker_model,
            session_id=session_id,
            thread_slug=thread_slug,
            brief_content=brief_content,
            rendered_events=rendered_events,
            thread_name=meta.get("name", thread_slug),
            scope=meta.get("scope", ""),
            max_state_tokens=debrief_cfg.max_state_tokens,
        )
        write_result = engine.thread_repository.record_debrief_episode(
            thread_slug=thread_slug,
            session_id=session_id,
            episode_markdown=output.episode_markdown,
            brief_markdown=output.brief_markdown,
            now=datetime.now(),
            state_content=brief_content,
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


async def generate_debrief_output(
    provider: Any,
    *,
    worker_model: str,
    session_id: str,
    thread_slug: str,
    brief_content: str,
    rendered_events: str,
    thread_name: str = "",
    scope: str = "",
    max_state_tokens: int = _DEFAULT_MAX_STATE_TOKENS,
) -> DebriefOutput:
    """Generate episode + updated brief via worker model with fallback."""
    trimmed_brief = trim_text_to_token_budget(
        brief_content, max_state_tokens, model=worker_model, suffix=_TRUNCATION_SUFFIX
    )
    header_parts = [f"Thread: {thread_slug}"]
    if thread_name and thread_name != thread_slug:
        header_parts.append(f"Name: {thread_name}")
    if scope:
        header_parts.append(f"Scope: {scope}")
    header_parts.append(f"Session: {session_id}")
    prompt = (
        "\n".join(header_parts) + f"\n\nCurrent BRIEF.md:\n{trimmed_brief}\n\n"
        f"Session events:\n{rendered_events}"
    )
    try:
        response = await provider.chat(
            messages=[
                {"role": "system", "content": _DEBRIEF_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            tools=[],
            model=worker_model,
        )
        if response.content and isinstance(response.content, str):
            return _parse_debrief_response(response.content)
    except Exception as e:
        logger.warning(f"Session debrief generation failed for {thread_slug}: {e}")

    return DebriefOutput(
        episode_markdown=_build_fallback_episode_markdown(
            session_id=session_id, thread_slug=thread_slug
        ),
        brief_markdown=None,
    )


def _build_fallback_episode_markdown(*, session_id: str, thread_slug: str) -> str:
    """Build deterministic fallback episode markdown when generation fails."""
    date_prefix = datetime.now().strftime("%Y-%m-%d")
    return (
        f"# {date_prefix}: Session update for {thread_slug}\n\n"
        f"Session: {session_id}\n\n"
        "## Summary\n"
        "- Session debrief fallback — worker model generation failed.\n"
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
    "DEBRIEF_ACTION_CANCEL",
    "DEBRIEF_ACTION_CONFIRM",
    "DEBRIEF_ACTION_KEY",
    "DEBRIEF_CANCEL_CB",
    "DEBRIEF_CONFIRM_CB",
    "DebriefOutput",
    "build_debrief_confirmation_message",
    "extract_thread_slug_from_value",
    "extract_touched_threads",
    "format_session_events_for_prompt",
    "generate_debrief_output",
    "is_debrief_action_message",
    "is_debrief_confirm_message",
    "resolve_debrief_thread_order",
    "run_session_debrief",
]
