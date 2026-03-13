"""Background subagent completion queue and continuation runtime."""

from __future__ import annotations

import asyncio
import copy
from typing import TYPE_CHECKING, Any

from loguru import logger

from hal.bus.events import OutboundMessage, SubagentCompleteEvent
from hal.runtime.session import build_persisted_session_history
from hal.workspace import SessionRepository

from .processing import (
    _normalize_final_content,
    _should_record_assistant_history,
)
from .subagent_injection import _SUBAGENT_RUNTIME_MAX_TOKENS, _build_subagent_injection

if TYPE_CHECKING:
    from . import AgentEngine


class _EngineBackgroundResume:
    """Maintain detached subagent completions and resume the same session loop."""

    def __init__(self, *, engine: "AgentEngine") -> None:
        self._engine = engine
        self._session_repository = SessionRepository(engine.workspace)
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

    def set_session_active(self, session_id: str, active: bool) -> None:
        """Track whether a session currently has an active engine loop."""
        if active:
            self._active_sessions.add(session_id)
        else:
            self._active_sessions.discard(session_id)

    def store_session_snapshot(
        self,
        *,
        session_id: str,
        channel: str,
        chat_id: str,
        messages: list[dict[str, Any]],
        final_content: str | None,
    ) -> None:
        """Store the full loop context for potential detached continuation."""
        snapshot = copy.deepcopy(messages)
        if final_content:
            snapshot.append({"role": "assistant", "content": final_content})
        self._session_snapshots[session_id] = snapshot
        self._session_routes[session_id] = (channel, chat_id)
        try:
            self._session_repository.write_snapshot(
                session_key=session_id,
                channel=channel,
                chat_id=chat_id,
                messages=snapshot,
            )
        except Exception as error:
            logger.warning(f"Failed to write session snapshot: {error}")

    def clear_session_snapshot(self, session_id: str) -> None:
        """Drop cached and persisted snapshot state for one session."""
        self._session_snapshots.pop(session_id, None)
        self._session_routes.pop(session_id, None)
        try:
            self._session_repository.delete_snapshot(session_id)
        except Exception as error:
            logger.warning(f"Failed to delete session snapshot: {error}")

    async def queue_background_completion(self, event: SubagentCompleteEvent) -> None:
        """Queue detached subagent completions and continue same-session loop when idle."""
        if not event.background:
            return

        session_id = event.session_id
        if not session_id:
            return

        # Active loops consume runtime injections directly via per-loop subscribers.
        if session_id in self._active_sessions:
            return

        self._pending_background_events.setdefault(session_id, []).append(event)
        task = self._background_resume_tasks.get(session_id)
        if task and not task.done():
            return

        self._background_resume_tasks[session_id] = asyncio.create_task(
            self._resume_from_background(session_id)
        )

    async def _resume_from_background(self, session_id: str) -> None:
        """Resume a session loop from the last snapshot when detached results arrive."""
        try:
            while self._pending_background_events.get(session_id):
                if session_id in self._active_sessions:
                    await asyncio.sleep(0.1)
                    continue

                pending = self._dequeue_pending(session_id)
                if not pending:
                    break

                snapshot = self._load_resume_snapshot(session_id)
                if snapshot is None:
                    continue

                messages = self._append_runtime_injections(snapshot=snapshot, events=pending)
                final_content, meta = await self._run_resumed_loop(
                    session_id=session_id,
                    messages=messages,
                )
                final_content = _normalize_final_content(final_content)
                await self._finalize_resumed_turn(
                    session_id=session_id,
                    messages=messages,
                    final_content=final_content,
                    meta=meta,
                )
        finally:
            self._background_resume_tasks.pop(session_id, None)

    def _dequeue_pending(self, session_id: str) -> list[SubagentCompleteEvent]:
        """Pop the current queued background completion batch for a session."""
        return self._pending_background_events.pop(session_id, [])

    def _load_resume_snapshot(self, session_id: str) -> list[dict[str, Any]] | None:
        """Load snapshot needed to resume the detached loop."""
        snapshot = self._session_snapshots.get(session_id)
        if snapshot:
            return copy.deepcopy(snapshot)

        persisted = self._session_repository.read_snapshot(session_id)
        if persisted is None:
            return None
        recovered = copy.deepcopy(persisted.messages)
        self._session_snapshots[session_id] = recovered
        self._session_routes[session_id] = (persisted.channel, persisted.chat_id)
        return copy.deepcopy(recovered)

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

    async def _run_resumed_loop(
        self,
        *,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> tuple[str, Any]:
        """Resume the engine loop once with injected background completions."""
        route = self._session_routes.get(session_id)
        if route:
            channel, chat_id = route
            self._engine._update_tool_contexts(channel, chat_id)
        self.set_session_active(session_id, True)
        try:
            final_content, meta, _ = await self._engine._execute_loop(
                messages=messages,
                max_iterations=self._engine.max_iterations,
                session_id=session_id,
            )
        finally:
            self.set_session_active(session_id, False)
        return final_content, meta

    async def _finalize_resumed_turn(
        self,
        *,
        session_id: str,
        messages: list[dict[str, Any]],
        final_content: str,
        meta: Any,
    ) -> None:
        """Persist resumed output and emit outbound response."""
        route = self._session_routes.get(session_id)
        channel, chat_id = route if route else ("unknown", "unknown")

        record_assistant_history = _should_record_assistant_history(final_content)
        session_history = build_persisted_session_history(
            working_set_messages=messages,
            final_content=final_content,
            include_final_assistant=record_assistant_history,
        )
        session_history = await self._engine._maybe_compact_session_history(
            session_id=session_id,
            history=session_history,
            token_model=self._engine.provider.resolve_model(self._engine.model),
        )
        self._engine._set_session_history(session_id, session_history)
        self._engine._touch_session(session_id)

        snapshot_messages = self._engine._build_session_snapshot_messages(
            session_id=session_id,
            token_model=self._engine.provider.resolve_model(self._engine.model),
        )
        self.store_session_snapshot(
            session_id=session_id,
            channel=channel,
            chat_id=chat_id,
            messages=snapshot_messages,
            final_content=None,
        )

        if bool(getattr(self._engine.tools.get("message"), "sent_in_turn", False)):
            return
        await self._engine.bus.publish_outbound(
            OutboundMessage(channel=channel, chat_id=chat_id, content=final_content)
        )
