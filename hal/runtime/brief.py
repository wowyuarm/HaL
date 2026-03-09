"""Session brief worker — fs-tool-equipped mini-agent for post-session knowledge capture."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from hal.capabilities.tools.fs import FsTool
from hal.capabilities.tools.registry import ToolRegistry
from hal.context.message_building import add_assistant_message, add_tool_result
from hal.runtime.debrief import format_session_events_for_prompt, resolve_debrief_thread_order
from hal.runtime.loop import LoopMetadata, run_tool_loop

_BRIEF_MAX_ITERATIONS = 30

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
    thread_order = resolve_debrief_thread_order(
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
# Helpers
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
