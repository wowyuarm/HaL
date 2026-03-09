"""Session brief worker — fs-tool-equipped mini-agent for post-session knowledge capture.

Also contains shared helpers for thread extraction, event rendering, and thread ordering
used by both the brief worker and other runtime components (e.g. engine hooks).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from loguru import logger

from hal.capabilities.tools.fs import FsTool
from hal.capabilities.tools.registry import ToolRegistry
from hal.context.message_building import add_assistant_message, add_tool_result
from hal.context.token_budget import estimate_text_tokens, trim_text_to_token_budget
from hal.runtime.loop import LoopMetadata, run_tool_loop
from hal.workspace.events import EventEntry

_BRIEF_MAX_ITERATIONS = 30

# ---------------------------------------------------------------------------
# Thread slug extraction
# ---------------------------------------------------------------------------

_THREAD_PATH_RE = re.compile(r"(?:^|/)threads/([^/]+)/")

# Token-based budget defaults (overridable via BriefConfig)
_DEFAULT_MAX_EVENT_TOKENS = 1500
_DEFAULT_MAX_PROMPT_TOKENS = 100_000
_TRUNCATION_SUFFIX = "\n...[truncated]"


def extract_thread_slug_from_value(value: Any) -> str | None:
    """Extract thread slug from arbitrary string value containing a threads/<slug>/ path."""
    if not isinstance(value, str):
        return None
    normalized = value.replace("\\", "/")
    match = _THREAD_PATH_RE.search(normalized)
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


# ---------------------------------------------------------------------------
# Event rendering
# ---------------------------------------------------------------------------


def format_session_events_for_prompt(
    events: list[EventEntry],
    *,
    model: str | None = None,
    max_tokens: int = _DEFAULT_MAX_PROMPT_TOKENS,
    max_event_tokens: int = _DEFAULT_MAX_EVENT_TOKENS,
) -> str:
    """Render compact event stream for worker-model input.

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

    # Tool-call events: show "tool → result_preview" when available.
    tool_name = payload.get("tool")
    if isinstance(tool_name, str) and tool_name.strip():
        result_preview = payload.get("result_preview", "")
        if isinstance(result_preview, str) and result_preview.strip():
            text = f"{tool_name} \u2192 {result_preview.strip()}".replace("\n", " ")
            return _cap_text(text, model=model, max_event_tokens=max_event_tokens)
        return tool_name.strip()

    for key in ("content", "label", "status"):
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
# Thread ordering
# ---------------------------------------------------------------------------


def resolve_brief_thread_order(
    *,
    context_registry: object,
    touched_threads: set[str],
) -> list[str]:
    """Resolve thread order using registry priority and one-hop relations."""
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


# ---------------------------------------------------------------------------
# Brief worker entry point
# ---------------------------------------------------------------------------


async def run_session_brief(engine: Any, session_key: str, *, user_prompt: str = "") -> None:
    """Run brief worker agent for one closed session.

    Reads session events, builds a restricted tool environment, and executes
    a tool-calling loop so the worker can autonomously read/write thread files
    under the ``work/`` directory.
    """
    state = engine._session_states.get(session_key)
    if state is None:
        logger.warning(f"Brief worker: no session state for {session_key}")
        return

    session_id = state.session_id
    brief_cfg = engine._engine_config.brief
    worker_model = engine._worker_model
    worker_provider = engine._worker_provider

    # 1. Read session events
    events = engine.memory.event_log.read_session(session_id)
    rendered_events = format_session_events_for_prompt(
        events,
        model=worker_model,
        max_tokens=brief_cfg.max_prompt_tokens,
        max_event_tokens=brief_cfg.max_event_tokens,
    )

    # 2. Resolve thread order and metadata
    thread_order = resolve_brief_thread_order(
        context_registry=engine.context_registry,
        touched_threads=state.touched_threads,
    )
    thread_meta = _collect_thread_meta(engine)

    # 3. Build tools, prompts, and messages
    tools = _build_brief_tools(engine.workspace)
    system_prompt = _build_brief_system_prompt()
    user_msg = _build_brief_user_prompt(
        rendered_events=rendered_events,
        touched_threads=state.touched_threads,
        thread_order=thread_order,
        thread_meta=thread_meta,
        user_prompt=user_prompt,
        session_id=session_id,
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    # 4. Execute brief worker loop
    max_iterations = brief_cfg.max_iterations
    hooks = _BriefLoopHooks()
    try:
        final_content, meta = await run_tool_loop(
            provider=worker_provider,
            model=worker_model,
            tools=tools,
            messages=messages,
            max_iterations=max_iterations,
            hooks=hooks,
            add_assistant_message=add_assistant_message,
            add_tool_result=add_tool_result,
        )
    except Exception as e:
        logger.error(f"Brief worker loop failed: {e}")
        final_content = None
        meta = LoopMetadata()

    # 5. Index any written episode files
    indexed_chunks = await _index_written_episodes(engine, meta)

    # 6. Send completion summary
    summary = _format_completion_summary(final_content, meta)
    from hal.bus.events import OutboundMessage

    await engine.bus.publish_outbound(
        OutboundMessage(
            channel=state.channel,
            chat_id=state.chat_id,
            content=summary,
            metadata={"system_meta": True, "kind": "session_brief_complete"},
        )
    )

    # 7. Record event
    engine.memory.record_event(
        session_id=session_id,
        event_type="session_brief_complete",
        channel=state.channel,
        chat_id=state.chat_id,
        payload={
            "iterations": meta.iterations,
            "files_modified": meta.files_modified,
            "indexed_chunks": indexed_chunks,
        },
    )
    logger.info(
        f"Brief worker complete: {meta.iterations} iterations, "
        f"{len(meta.files_modified)} files modified"
    )


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------


def _build_brief_tools(workspace: Path) -> ToolRegistry:
    """Create restricted ToolRegistry with fs tool limited to work/ directory."""
    work_dir = workspace / "work"
    registry = ToolRegistry()
    registry.register(FsTool(allowed_dir=work_dir, base_dir=work_dir))
    return registry


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_BRIEF_SYSTEM_PROMPT = """\
You are a brief maintainer for HaL's collaboration workspace.

After each session, you capture what happened into the thread system:
- **Episodes**: immutable records of what a session contributed to a thread.
- **BRIEF.md**: living document that orients the next session on a thread.

## Available tool

You have one tool: `fs` with actions `read`, `write`, `edit`, `list`.
All paths are relative to the `work/` directory (e.g. `threads/<slug>/BRIEF.md`).

## Workflow

1. Read the current BRIEF.md for each relevant thread.
2. Analyze the session events to understand what happened.
3. For each thread that was meaningfully advanced:
   a. Write an episode file to `threads/<slug>/episodes/<filename>.md`
      - Episode filename format: `YYYY-MM-DD-<slug>-<session_id>.md`
      - Start with `# YYYY-MM-DD: <title>` heading
      - Content: what happened, decisions made, outcomes. Concise and factual.
   b. Update `threads/<slug>/BRIEF.md`:
      - Evolve the brief to reflect current state (not a log — a living document).
      - Maintain a `## Recent Episodes` section at the end with links:
        `- [Episode title](episodes/<filename>.md)`
4. If a session didn't meaningfully advance a thread, skip it.

## BRIEF.md guidelines

The brief answers: Where do things stand? What's been decided? What needs attention?
Different threads warrant different structures. Remove outdated information.
Update status. The brief is what a collaborator reads at the start of the next session.

## Workspace structure

```
threads/<slug>/BRIEF.md          # Living thread state
threads/<slug>/THREAD.yaml       # Thread metadata (read-only reference)
threads/<slug>/episodes/          # Immutable episode records
```

## Output

After completing your work, output a concise summary of what you did:
which threads you updated, episodes written, and any notable observations.
"""


def _build_brief_system_prompt() -> str:
    """Return the brief worker system prompt."""
    return _BRIEF_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# User prompt
# ---------------------------------------------------------------------------


def _build_brief_user_prompt(
    *,
    rendered_events: str,
    touched_threads: set[str],
    thread_order: list[str],
    thread_meta: dict[str, dict[str, str]],
    user_prompt: str,
    session_id: str,
) -> str:
    """Build XML-structured user prompt for the brief worker."""
    parts: list[str] = []

    # Session events
    parts.append(f'<session id="{session_id}">')
    parts.append(f"<events>\n{rendered_events}\n</events>")
    parts.append("</session>")

    # Thread metadata
    parts.append("<threads>")
    for slug in thread_order:
        meta = thread_meta.get(slug, {})
        name = meta.get("name", slug)
        scope = meta.get("scope", "")
        touched = "true" if slug in touched_threads else "false"
        parts.append(
            f'  <thread slug="{slug}" name="{name}" scope="{scope}" touched="{touched}" />'
        )
    parts.append("</threads>")

    # Optional user guidance
    if user_prompt.strip():
        parts.append(f"<guidance>{user_prompt.strip()}</guidance>")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Loop hooks
# ---------------------------------------------------------------------------


class _BriefLoopHooks:
    """Minimal loop hooks for the brief worker."""

    def before_llm_call(self, messages: list[dict[str, Any]], meta: LoopMetadata) -> None:
        if meta.iterations > 0:
            logger.debug(f"Brief worker: iteration {meta.iterations + 1}")

    def on_tool_result(
        self,
        tool_name: str,
        tool_id: str,
        arguments: dict[str, Any],
        result: str,
        messages: list[dict[str, Any]],
        meta: LoopMetadata,
    ) -> None:
        action = arguments.get("action", "")
        path = arguments.get("path", "")
        logger.debug(f"Brief worker: {tool_name}.{action}({path})")

    async def on_no_tool_calls(
        self,
        messages: list[dict[str, Any]],
        response: Any,
        meta: LoopMetadata,
    ) -> bool:
        return False

    async def on_tool_calls_start(
        self,
        tool_calls: list[Any],
        assistant_content: str | None,
        meta: LoopMetadata,
    ) -> None:
        return None

    async def on_loop_exhausted(
        self,
        messages: list[dict[str, Any]],
        meta: LoopMetadata,
    ) -> str | None:
        # Nudge the worker to wrap up
        messages.append(
            {
                "role": "user",
                "content": "[System] Iteration limit reached. Output your work summary now.",
            }
        )
        return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _collect_thread_meta(engine: Any) -> dict[str, dict[str, str]]:
    """Build thread metadata lookup from context registry."""
    meta: dict[str, dict[str, str]] = {}
    try:
        for item in engine.context_registry.thread_snapshot():
            slug = str(item.get("slug", ""))
            if slug:
                meta[slug] = {
                    "name": str(item.get("name", slug)),
                    "scope": str(item.get("scope", "")),
                }
    except Exception:
        pass
    return meta


async def _index_written_episodes(engine: Any, meta: LoopMetadata) -> int:
    """Index any episode files written by the brief worker."""
    episode_paths = [Path(p) for p in meta.files_modified if "episodes/" in p and p.endswith(".md")]
    if not episode_paths or engine._memory_search is None:
        return 0
    try:
        return await engine._memory_search.index_paths(episode_paths)
    except Exception as e:
        logger.warning(f"Episode indexing after brief failed: {e}")
        return 0


def _format_completion_summary(final_content: str | None, meta: LoopMetadata) -> str:
    """Format a user-facing brief completion message."""
    if final_content and final_content.strip():
        return final_content.strip()
    if meta.files_modified:
        files = ", ".join(Path(f).name for f in meta.files_modified[:5])
        suffix = f" (+{len(meta.files_modified) - 5} more)" if len(meta.files_modified) > 5 else ""
        return f"Session brief complete. Updated: {files}{suffix}"
    return "Session brief complete (no changes needed)."
