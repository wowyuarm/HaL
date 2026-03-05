"""Background subagent completion queue and continuation runtime."""

from __future__ import annotations

import asyncio
import copy
from typing import TYPE_CHECKING, Any

from loguru import logger

from hal.bus.events import OutboundMessage, SubagentCompleteEvent

from .processing import _should_record_assistant_history
from .subagent_injection import _SUBAGENT_RUNTIME_MAX_TOKENS, _build_subagent_injection

if TYPE_CHECKING:
    from . import AgentEngine


class _EngineBackgroundResume:
    """Maintain detached subagent completions and resume the same session loop."""

    def __init__(self, *, engine: "AgentEngine") -> None:
        self._engine = engine
        self._active_sessions: set[str] = set()
        self._session_snapshots: dict[str, list[dict[str, Any]]] = {}
        self._session_routes: dict[str, tuple[str, str]] = {}
        self._pending_background_events: dict[str, list[SubagentCompleteEvent]] = {}
        self._background_resume_tasks: dict[str, asyncio.Task[None]] = {}

    def close(self) -> None:
        """Cancel queued resume tasks."""
        for task in self._background_resume_tasks.values():
            task.cancel()
        self._background_resume_tasks.clear()

    def set_session_active(self, session_key: str, active: bool) -> None:
        """Track whether a session currently has an active engine loop."""
        if active:
            self._active_sessions.add(session_key)
        else:
            self._active_sessions.discard(session_key)

    def store_session_snapshot(
        self,
        *,
        session_key: str,
        channel: str,
        chat_id: str,
        messages: list[dict[str, Any]],
        final_content: str | None,
    ) -> None:
        """Store the full loop context for potential detached continuation."""
        snapshot = copy.deepcopy(messages)
        if final_content:
            snapshot.append({"role": "assistant", "content": final_content})
        self._session_snapshots[session_key] = snapshot
        self._session_routes[session_key] = (channel, chat_id)

    async def queue_background_completion(self, event: SubagentCompleteEvent) -> None:
        """Queue detached subagent completions and continue same-session loop when idle."""
        if not event.background:
            return

        session_key = event.session_key
        if not session_key and event.channel and event.chat_id:
            session_key = f"{event.channel}:{event.chat_id}"
        if not session_key:
            return

        # Active loops consume runtime injections directly via per-loop subscribers.
        if session_key in self._active_sessions:
            return

        self._pending_background_events.setdefault(session_key, []).append(event)
        task = self._background_resume_tasks.get(session_key)
        if task and not task.done():
            return

        self._background_resume_tasks[session_key] = asyncio.create_task(
            self._resume_from_background(session_key)
        )

    async def _resume_from_background(self, session_key: str) -> None:
        """Resume a session loop from the last snapshot when detached results arrive."""
        try:
            while self._pending_background_events.get(session_key):
                if session_key in self._active_sessions:
                    await asyncio.sleep(0.1)
                    continue

                pending = self._dequeue_pending(session_key)
                if not pending:
                    break

                context = self._load_resume_context(session_key)
                if context is None:
                    continue
                channel, chat_id, snapshot = context

                messages = self._append_runtime_injections(snapshot=snapshot, events=pending)
                await self._await_summary_barrier(session_key)
                final_content, meta = await self._run_resumed_loop(
                    session_key=session_key,
                    channel=channel,
                    chat_id=chat_id,
                    messages=messages,
                )
                if not final_content:
                    continue
                await self._finalize_resumed_turn(
                    session_key=session_key,
                    channel=channel,
                    chat_id=chat_id,
                    messages=messages,
                    final_content=final_content,
                    meta=meta,
                )
        finally:
            self._background_resume_tasks.pop(session_key, None)

    def _dequeue_pending(self, session_key: str) -> list[SubagentCompleteEvent]:
        """Pop the current queued background completion batch for a session."""
        return self._pending_background_events.pop(session_key, [])

    def _load_resume_context(
        self, session_key: str
    ) -> tuple[str, str, list[dict[str, Any]]] | None:
        """Load route and snapshot needed to resume the detached loop."""
        snapshot = self._session_snapshots.get(session_key)
        route = self._session_routes.get(session_key)
        if not snapshot or not route:
            return None
        channel, chat_id = route
        return channel, chat_id, snapshot

    def _append_runtime_injections(
        self,
        *,
        snapshot: list[dict[str, Any]],
        events: list[SubagentCompleteEvent],
    ) -> list[dict[str, Any]]:
        """Build resumed message list by appending queued background injections."""
        messages = copy.deepcopy(snapshot)
        for event in events:
            runtime_inject = _build_subagent_injection(
                label=event.label,
                content=event.content,
                status=event.status,
                background=True,
                record_id=event.record_id,
                artifact_path=event.artifact_path,
                total_tokens=event.total_tokens,
                tools_used=event.tools_used,
                tool_call_counts=event.tool_call_counts,
                has_side_effects=event.has_side_effects,
                files_modified=event.files_modified,
                commands_run=event.commands_run,
                tool_errors=event.tool_errors,
                missing_artifacts=event.missing_artifacts,
                max_tokens=_SUBAGENT_RUNTIME_MAX_TOKENS,
            )
            messages.append({"role": "user", "content": runtime_inject})
        return messages

    async def _await_summary_barrier(self, session_key: str) -> None:
        """Wait briefly for prior summary persistence to finish before resuming."""
        task = self._engine._pending_summaries.pop(session_key, None)
        if not task:
            return
        try:
            await asyncio.wait_for(
                task,
                timeout=self._engine._engine_config.summary_barrier_timeout_s,
            )
        except (asyncio.TimeoutError, Exception) as error:
            logger.warning(f"Summary barrier: {error}")

    async def _run_resumed_loop(
        self,
        *,
        session_key: str,
        channel: str,
        chat_id: str,
        messages: list[dict[str, Any]],
    ) -> tuple[str, Any]:
        """Resume the engine loop once with injected background completions."""
        self._engine._update_tool_contexts(channel, chat_id)
        self.set_session_active(session_key, True)
        try:
            final_content, meta, _ = await self._engine._execute_loop(
                messages=messages,
                max_iterations=self._engine.max_iterations,
                session_key=session_key,
                channel=channel,
                chat_id=chat_id,
            )
        finally:
            self.set_session_active(session_key, False)
        return final_content, meta

    async def _finalize_resumed_turn(
        self,
        *,
        session_key: str,
        channel: str,
        chat_id: str,
        messages: list[dict[str, Any]],
        final_content: str,
        meta: Any,
    ) -> None:
        """Persist resumed output, queue summary, and emit outbound response."""
        record_assistant_history = _should_record_assistant_history(final_content)
        if record_assistant_history:
            self._engine.memory.record_conversation(
                channel=channel,
                chat_id=chat_id,
                role="assistant",
                content=final_content,
            )
        summary_task = None
        if record_assistant_history:
            summary_task = self._engine._trigger_summary(meta, final_content, channel, chat_id)
        if summary_task:
            self._engine._pending_summaries[session_key] = summary_task

        self.store_session_snapshot(
            session_key=session_key,
            channel=channel,
            chat_id=chat_id,
            messages=messages,
            final_content=final_content if record_assistant_history else None,
        )

        if bool(getattr(self._engine.tools.get("message"), "sent_in_turn", False)):
            return
        await self._engine.bus.publish_outbound(
            OutboundMessage(channel=channel, chat_id=chat_id, content=final_content)
        )
