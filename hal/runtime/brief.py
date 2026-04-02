"""Session brief worker — fs-tool-equipped mini-agent for post-session knowledge capture.

Also contains shared helpers for thread extraction, event rendering, and thread ordering
used by both the brief worker and other runtime components (e.g. engine hooks).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from loguru import logger

from hal.capabilities.tools.fs import EditFileTool, ReadFileTool, WriteFileTool
from hal.capabilities.tools.registry import ToolRegistry
from hal.context.message_building import add_assistant_message, add_tool_result
from hal.domain.events import BRIEF_COMPLETED, STATUS_CHANGED, SessionEvent
from hal.runtime.loop import LoopMetadata, run_tool_loop
from hal.runtime.worker_inputs import build_event_input_lines, render_worker_input_lines
from hal.workspace.layout import WorkspaceLayout
from hal.workspace.thread_refs import ThreadRefsRepository, ThreadSessionRef

_BRIEF_MAX_ITERATIONS = 30
_ERROR_CALLING_LLM_PREFIX = "Error calling LLM:"

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
    events: list[SessionEvent],
    *,
    model: str | None = None,
    max_tokens: int = _DEFAULT_MAX_PROMPT_TOKENS,
    max_event_tokens: int = _DEFAULT_MAX_EVENT_TOKENS,
) -> str:
    """Render compact event stream for worker-model input.

    Each event is individually capped at *max_event_tokens*. The full
    rendered output is then trimmed to *max_tokens* as a safety net.
    """
    return render_worker_input_lines(
        build_event_input_lines(events),
        model=model,
        max_line_tokens=max_event_tokens,
        max_total_tokens=max_tokens,
        empty_text="- (no events)",
        line_suffix="...[truncated]",
        total_suffix=_TRUNCATION_SUFFIX,
    )


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


async def run_session_brief(engine: Any, session_id: str, *, user_prompt: str = "") -> None:
    """Run brief worker agent for one closed session.

    Reads session events, builds a restricted tool environment, and executes
    a tool-calling loop so the worker can autonomously read/write thread files
    under the ``work/`` directory.
    """
    state = engine._sessions.get(session_id)
    if state is None:
        logger.warning(f"Brief worker: no session state for {session_id}")
        return

    # Persist the brief prompt on the manifest so restarts can recover it
    # without scanning the event log.
    state.manifest.brief_prompt = user_prompt
    engine._session_store.write_manifest(session_id, state.manifest)

    channel = state.manifest.channel
    chat_id = state.manifest.chat_id
    brief_cfg = engine._engine_config.brief
    worker_model = engine._worker_model
    worker_provider = engine._worker_provider

    # 1. Read session events
    events = engine._session_store.read_events(session_id)
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
        primary_thread=state.primary_thread,
        mounted_threads=state.mounted_threads,
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    # 4. Execute brief worker loop
    max_iterations = brief_cfg.max_iterations
    hooks = _BriefLoopHooks()
    worker_failed = False
    failure_reason: str | None = None
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
        worker_failed = True
        failure_reason = str(e)
    else:
        if _brief_result_failed(final_content, meta):
            worker_failed = True
            failure_reason = _brief_failure_reason(final_content)
            logger.error(f"Brief worker failed: {failure_reason}")

    if worker_failed:
        state.manifest.status = "active"
        state.manifest.ended_at = None
        state.manifest.brief_prompt = None
        state.brief_task = None
        engine._session_store.write_manifest(session_id, state.manifest)
        engine._refresh_session_snapshot(session_id)
        await state.event_publisher.emit(
            STATUS_CHANGED,
            actor="worker",
            payload={
                "status": "active",
                "kind": "session_brief_failed",
                "message": _format_failure_summary(failure_reason),
            },
        )

        if channel and chat_id:
            from hal.bus.events import OutboundMessage

            await engine.bus.publish_outbound(
                OutboundMessage(
                    channel=channel,
                    chat_id=chat_id,
                    content=_format_failure_summary(failure_reason),
                    metadata={"system_meta": True, "kind": "session_brief_failed"},
                )
            )
        logger.warning(
            f"Brief worker failed: {meta.iterations} iterations, "
            f"{len(meta.files_modified)} files modified"
        )
        return

    # 5. Index any written episode files
    indexed_chunks = await _index_written_episodes(engine, meta)

    # 6. Write thread-to-session references
    _write_thread_session_refs(engine, state)

    # 7. Send completion summary
    summary = _format_completion_summary(final_content, meta)
    await state.event_publisher.emit(
        STATUS_CHANGED,
        actor="worker",
        payload={
            "status": "ended",
            "kind": "session_brief_complete",
            "message": summary,
        },
    )
    if channel and chat_id:
        from hal.bus.events import OutboundMessage

        await engine.bus.publish_outbound(
            OutboundMessage(
                channel=channel,
                chat_id=chat_id,
                content=summary,
                metadata={"system_meta": True, "kind": "session_brief_complete"},
            )
        )

    # 8. Record event and end the session only on successful completion.
    await state.event_publisher.emit(
        BRIEF_COMPLETED,
        actor="worker",
        refs={
            key: value
            for key, value in {
                "channel": channel,
                "chat_id": chat_id,
            }.items()
            if value
        },
        payload={
            "iterations": meta.iterations,
            "files_modified": meta.files_modified,
            "indexed_chunks": indexed_chunks,
            "threads_linked": sorted(_brief_target_threads(state)),
        },
    )
    await engine.end_session(
        session_id,
        status="ended",
        reason="brief_completed",
    )
    logger.info(
        f"Brief worker complete: {meta.iterations} iterations, "
        f"{len(meta.files_modified)} files modified"
    )


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------


def _build_brief_tools(workspace: Path) -> ToolRegistry:
    """Create restricted ToolRegistry with file tools limited to work/ directory."""
    work_dir = workspace / "work"
    registry = ToolRegistry()
    registry.register(ReadFileTool(allowed_dir=work_dir, base_dir=work_dir))
    registry.register(WriteFileTool(allowed_dir=work_dir, base_dir=work_dir))
    registry.register(EditFileTool(allowed_dir=work_dir, base_dir=work_dir))
    return registry


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_BRIEF_SYSTEM_PROMPT = """\
You are the brief maintainer for HaL's thread workspace.

Your job is not to summarize a session.
Your job is to preserve the minimum state needed for a future session \
to re-enter the work without re-heating old context.

Not every session deserves an update. \
If nothing materially changed for future collaboration, output a \
one-line summary and do not modify any files.

## What a thread is

A thread is a long-lived collaboration track. \
It may be a project, a study topic, a recurring coordination concern, \
or an ongoing design question.

Each thread has:
- BRIEF.md: the current working state for re-entry
- episodes/: immutable session records
- THREAD.yaml: thread identity and guidance (read-only reference)

## Session structure

Each thread in the candidate list has a `role` indicating its relationship \
to the session:
- `primary`: the session's main focus, chosen by the user at start
- `mounted`: additional threads the user explicitly scoped in
- `touched`: threads whose files were accessed during the session
- `related`: threads connected via `related_threads` metadata

Primary and mounted threads reflect explicit user intent — they deserve \
careful consideration. Touched threads may be incidental (a tool happened \
to read a file) — use event content to judge whether the thread's state \
actually changed. Related threads are context only; update them only when \
the session clearly moved their state.

## How to judge relevance

Use thread metadata as a lens:
- `goal`: the endpoint or purpose of the thread
- `core_question`: the persistent tension the thread keeps working through
- `brief_hints`: soft guidance about what this thread's BRIEF should \
preserve or avoid

Treat `brief_hints` as guidance, not a rule. \
If it conflicts with the actual session signal, trust the session signal.

## What is worth preserving

Preserve only what will help the next session do better work:
- Stable decisions, including decisions not to do something
- Changed judgments or perspective shifts
- Unresolved tensions
- Important open questions
- The current focus
- The next useful re-entry point
- Meaningful links to other threads

Do not preserve:
- Chronological recap
- Tool-by-tool replay
- Generic status wording
- Trivial chat, tests, or motion without consequence
- Details already captured elsewhere unless the brief needs the conclusion

If nothing is worth preserving: output a one-line summary and stop. \
Do NOT create or modify any files.

## How to update a BRIEF

A BRIEF is a living state document, not a log. \
Write it so a future session can quickly answer:
- What matters now?
- What seems true now?
- What is still unresolved?
- Where should we pick up?

Do not default to a fixed template. \
Use whatever structure fits the thread naturally.

Good BRIEFs often include, when relevant:
- Current focus
- Stable judgments
- Unresolved tensions
- Re-entry point

Remove stale or superseded content. \
Preserve useful structure when it still serves the thread. \
Do not churn headings just to make the file look newly rewritten.

## Inbox

If something worth preserving doesn't belong to any existing thread, \
write a note to `inbox/<YYYY-MM-DD>-<title>.md` with a `# <title>` heading.

## Available tools

You have three tools: `read`, `write`, and `edit`.
All paths are relative to the `work/` directory (e.g. `threads/<slug>/BRIEF.md`).

## Workflow (only when writing is warranted)

1. Read the current BRIEF.md for each candidate thread.
2. Use the session events plus thread metadata to decide whether the \
thread's state changed.
3. For each thread worth updating:
   a. Write an episode to `threads/<slug>/episodes/<filename>.md`
      - Filename: `YYYY-MM-DD-<slug>-<session_id>.md`
      - Start with `# YYYY-MM-DD: <title>` heading
      - Content: what emerged, decisions made, open questions. Concise.
   b. Update `threads/<slug>/BRIEF.md`:
      - Evolve to reflect current state.
      - Keep a `## Recent Episodes` section at the end with links:
        `- [Episode title](episodes/<filename>.md)`

## Output

End with a concise summary:
- Which threads you updated, and why
- Which touched threads you did not update, and why
- Any inbox notes you wrote

If no updates were needed, say so in one line.
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
    primary_thread: str | None = None,
    mounted_threads: set[str] | None = None,
) -> str:
    """Build XML-structured user prompt for the brief worker."""
    parts: list[str] = []
    _mounted = mounted_threads or set()

    # Session events
    parts.append(f'<session id="{session_id}">')
    parts.append(f"<events>\n{rendered_events}\n</events>")
    parts.append("</session>")

    # Thread metadata — use sub-elements instead of attributes to handle
    # multi-line content (scope, core_question) without escaping issues.
    parts.append("<threads>")
    for slug in thread_order:
        meta = thread_meta.get(slug, {})
        role = _thread_role(slug, primary_thread, _mounted, touched_threads)
        thread_lines = [f'  <thread slug="{slug}" role="{role}">']
        thread_lines.append(f"    <name>{meta.get('name', slug)}</name>")
        description = meta.get("description", "")
        if description:
            thread_lines.append(f"    <goal>{description}</goal>")
        scope = meta.get("scope", "")
        if scope:
            thread_lines.append(f"    <scope>{scope}</scope>")
        core_question = meta.get("core_question", "")
        if core_question:
            thread_lines.append(f"    <core_question>{core_question}</core_question>")
        brief_hints = meta.get("brief_hints", "")
        if brief_hints:
            thread_lines.append(f"    <brief_hints>{brief_hints}</brief_hints>")
        thread_lines.append("  </thread>")
        parts.append("\n".join(thread_lines))
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


def _thread_role(
    slug: str,
    primary_thread: str | None,
    mounted_threads: set[str],
    touched_threads: set[str],
) -> str:
    """Return the most specific role for a thread in the brief worker prompt."""
    if slug == primary_thread:
        return "primary"
    if slug in mounted_threads:
        return "mounted"
    if slug in touched_threads:
        return "touched"
    return "related"


def _collect_thread_meta(engine: Any) -> dict[str, dict[str, str]]:
    """Build thread metadata lookup from thread repository.

    Reads directly from the repository instead of the registry snapshot to
    avoid ``max_thread_registry_size`` truncation — the brief worker must
    see metadata for every thread in the candidate list.
    """
    meta: dict[str, dict[str, str]] = {}
    try:
        entries = engine.thread_repository.collect_registry_entries(max_entries=100)
        for entry in entries:
            meta[entry.slug] = {
                "name": entry.name,
                "description": entry.description,
                "scope": entry.scope,
                "core_question": entry.core_question,
                "brief_hints": entry.brief_hints,
            }
    except Exception:
        pass
    return meta


async def _index_written_episodes(engine: Any, meta: LoopMetadata) -> int:
    """Index any episode files written by the brief worker."""
    episode_paths = [Path(p) for p in meta.files_modified if "episodes/" in p and p.endswith(".md")]
    if not episode_paths or engine._recall_index is None:
        return 0
    try:
        return await engine._recall_index.index_paths(episode_paths)
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


def _brief_result_failed(final_content: str | None, meta: LoopMetadata) -> bool:
    """Return True when the brief worker did not produce a usable result."""
    if isinstance(final_content, str) and final_content.strip().startswith(
        _ERROR_CALLING_LLM_PREFIX
    ):
        return True
    if meta.files_modified:
        return False
    return not bool(final_content and final_content.strip())


def _brief_failure_reason(final_content: str | None) -> str:
    """Normalize brief worker failures into one readable line."""
    if isinstance(final_content, str) and final_content.strip():
        return final_content.strip()
    return "Brief worker produced no usable result."


def _format_failure_summary(reason: str | None) -> str:
    """Format a user-facing failure message without implying completion."""
    if reason and reason.strip():
        return f"Session brief failed. {reason.strip()}"
    return "Session brief failed. The session is still active."


# ---------------------------------------------------------------------------
# Thread session refs
# ---------------------------------------------------------------------------


def _brief_target_threads(state: Any) -> list[str]:
    """Return thread slugs that should receive session refs after briefing."""
    selected: list[str] = []
    primary = state.primary_thread
    if primary:
        selected.append(primary)
    mounted_and_touched = sorted(state.mounted_threads & state.touched_threads)
    for slug in mounted_and_touched:
        if slug not in selected:
            selected.append(slug)
    return selected


def _write_thread_session_refs(engine: Any, state: Any) -> None:
    """Append thread-to-session refs for the threads covered by this brief."""
    targets = _brief_target_threads(state)
    if not targets:
        return
    refs_repo = ThreadRefsRepository(WorkspaceLayout(engine.workspace))
    primary = state.primary_thread
    for slug in targets:
        refs_repo.append_ref(
            slug,
            ThreadSessionRef(
                session_id=state.session_id,
                role="primary" if slug == primary else "mounted",
            ),
        )
