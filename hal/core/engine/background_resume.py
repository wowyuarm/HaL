"""Background subagent completion queue and continuation runtime."""

from __future__ import annotations

import asyncio
import copy
from typing import TYPE_CHECKING, Any

from loguru import logger

from hal.bus.events import OutboundMessage, SubagentCompleteEvent

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

                pending = self._pending_background_events.pop(session_key, [])
                if not pending:
                    break

                snapshot = self._session_snapshots.get(session_key)
                route = self._session_routes.get(session_key)
                if not snapshot or not route:
                    continue

                channel, chat_id = route
                messages = copy.deepcopy(snapshot)

                for event in pending:
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

                if task := self._engine._pending_summaries.pop(session_key, None):
                    try:
                        await asyncio.wait_for(
                            task,
                            timeout=self._engine._engine_config.summary_barrier_timeout_s,
                        )
                    except (asyncio.TimeoutError, Exception) as e:
                        logger.warning(f"Summary barrier: {e}")

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

                if not final_content:
                    continue

                self._engine.memory.record_conversation(
                    channel=channel,
                    chat_id=chat_id,
                    role="assistant",
                    content=final_content,
                )
                summary_task = self._engine._trigger_summary(meta, final_content, channel, chat_id)
                if summary_task:
                    self._engine._pending_summaries[session_key] = summary_task

                self.store_session_snapshot(
                    session_key=session_key,
                    channel=channel,
                    chat_id=chat_id,
                    messages=messages,
                    final_content=final_content,
                )

                if not bool(getattr(self._engine.tools.get("message"), "sent_in_turn", False)):
                    await self._engine.bus.publish_outbound(
                        OutboundMessage(channel=channel, chat_id=chat_id, content=final_content)
                    )
        finally:
            self._background_resume_tasks.pop(session_key, None)
