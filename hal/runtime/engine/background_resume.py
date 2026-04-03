"""Background subagent completion queue and continuation runtime."""

from __future__ import annotations

import asyncio
import copy
from typing import TYPE_CHECKING, Any

from loguru import logger

from hal.bus.events import OutboundMessage, SubagentCompleteEvent
from hal.domain.events import (
    ASSISTANT_MESSAGE_COMPLETED,
    LOOP_STARTED,
    MESSAGE_INJECTED,
    TURN_COMPLETED,
    TURN_FAILED,
    TURN_STARTED,
)
from hal.domain.session import build_turn_id
from hal.runtime.session import build_persisted_session_history
from hal.workspace import SessionRepository

from .processing import (
    _is_error_assistant_content,
    _normalize_final_content,
    _persist_completed_turn,
    build_error_recovery_inject,
)
from .subagent_injection import _SUBAGENT_RUNTIME_MAX_TOKENS, _build_subagent_injection
from .transport import SessionTransportContext

if TYPE_CHECKING:
    from . import AgentEngine


class _EngineBackgroundResume:
    """Maintain detached subagent completions and resume the same session loop."""

    def __init__(self, *, engine: "AgentEngine") -> None:
        self._engine = engine
        self._session_repository = SessionRepository(engine.workspace)
        self._active_sessions: set[str] = set()
        self._session_snapshots: dict[str, list[dict[str, Any]]] = {}
        self._session_transports: dict[str, SessionTransportContext] = {}
        self._pending_background_events: dict[str, list[SubagentCompleteEvent]] = {}
        self._background_resume_tasks: dict[str, asyncio.Task[None]] = {}

    def close(self) -> None:
        """Cancel queued resume tasks."""
        for task in self._background_resume_tasks.values():
            task.cancel()
        self._background_resume_tasks.clear()

    def set_session_active(self, session_id: str, active: bool) -> None:
        """Track whether a session currently has an in-flight turn."""
        if active:
            self._active_sessions.add(session_id)
        else:
            self._active_sessions.discard(session_id)

    def is_session_active(self, session_id: str) -> bool:
        """Return True while a session turn is currently in flight."""
        return session_id in self._active_sessions

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
        self._session_transports[session_id] = SessionTransportContext(
            channel=channel,
            chat_id=chat_id,
        )
        try:
            self._session_repository.write_snapshot(
                session_id=session_id,
                channel=channel,
                chat_id=chat_id,
                messages=snapshot,
            )
        except Exception as error:
            logger.warning(f"Failed to write session snapshot: {error}")

    def clear_session_snapshot(self, session_id: str) -> None:
        """Drop cached and persisted snapshot state for one session."""
        self._session_snapshots.pop(session_id, None)
        self._session_transports.pop(session_id, None)
        try:
            self._session_repository.delete_snapshot(session_id)
        except Exception as error:
            logger.warning(f"Failed to delete session snapshot: {error}")

    def close_session(self, session_id: str) -> None:
        """Drop detached continuation state for one completed session."""
        task = self._background_resume_tasks.pop(session_id, None)
        if task and not task.done():
            task.cancel()
        self._pending_background_events.pop(session_id, None)
        self._active_sessions.discard(session_id)
        self.clear_session_snapshot(session_id)

    def load_session_history(self, session_id: str) -> list[dict[str, Any]] | None:
        """Restore persisted replay history from the detached resume snapshot."""
        snapshot = self._load_resume_snapshot(session_id)
        if snapshot is None:
            return None
        return build_persisted_session_history(
            working_set_messages=snapshot,
            final_content="",
            include_final_assistant=False,
        )

    async def queue_background_completion(self, event: SubagentCompleteEvent) -> None:
        """Queue detached subagent completions and continue same-session loop when idle."""
        if not event.background:
            return

        session_id = event.session_id
        if not session_id:
            return
        if not self._session_is_resumable(session_id):
            self.close_session(session_id)
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
                if not self._session_is_resumable(session_id):
                    self.close_session(session_id)
                    break
                if session_id in self._active_sessions:
                    await asyncio.sleep(0.1)
                    continue

                pending = self._dequeue_pending(session_id)
                if not pending:
                    break

                snapshot = self._load_resume_snapshot(session_id)
                if snapshot is None:
                    continue

                self.set_session_active(session_id, True)
                try:
                    turn_id = await self._start_resumed_turn(
                        session_id=session_id,
                        queued_events=pending,
                    )
                    messages = await self._append_runtime_injections(
                        session_id=session_id,
                        turn_id=turn_id,
                        snapshot=snapshot,
                        events=pending,
                    )
                    final_content, meta = await self._run_resumed_loop(
                        session_id=session_id,
                        turn_id=turn_id,
                        messages=messages,
                    )
                    final_content = _normalize_final_content(final_content)
                    await self._finalize_resumed_turn(
                        session_id=session_id,
                        turn_id=turn_id,
                        messages=messages,
                        final_content=final_content,
                        meta=meta,
                    )
                finally:
                    self.set_session_active(session_id, False)
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
        self._session_transports[session_id] = SessionTransportContext(
            channel=persisted.channel,
            chat_id=persisted.chat_id,
        )
        return copy.deepcopy(recovered)

    def _session_is_resumable(self, session_id: str) -> bool:
        """Return True when detached completions may resume this session."""
        state = self._engine._sessions.get(session_id)
        if state is not None:
            return state.manifest.status == "active"

        manifest = self._engine._session_store.read_manifest(session_id)
        return manifest is not None and manifest.status == "active"

    async def _start_resumed_turn(
        self,
        *,
        session_id: str,
        queued_events: list[SubagentCompleteEvent],
    ) -> str:
        """Open a durable turn for detached background continuation."""
        state = self._engine.resume_session(session_id)
        if state is None:
            raise ValueError(f"Unknown session_id: {session_id}")
        state.manifest.turn_count += 1
        turn_id = build_turn_id(state.manifest.turn_count)
        await state.event_publisher.emit(
            TURN_STARTED,
            turn_id=turn_id,
            actor="engine",
            refs={
                "primary_thread": state.primary_thread,
                "mounted_threads": sorted(state.mounted_threads),
            },
            payload={
                "status": state.manifest.status,
                "origin": "background_resume",
                "queued_events": len(queued_events),
            },
        )
        await state.event_publisher.emit(
            LOOP_STARTED,
            turn_id=turn_id,
            actor="engine",
            payload={
                "origin": "background_resume",
                "max_iterations": self._engine.max_iterations,
            },
        )
        return turn_id

    async def _append_runtime_injections(
        self,
        *,
        session_id: str,
        turn_id: str,
        snapshot: list[dict[str, Any]],
        events: list[SubagentCompleteEvent],
    ) -> list[dict[str, Any]]:
        """Build resumed message list by appending queued background injections."""
        messages = copy.deepcopy(snapshot)
        state = self._engine.resume_session(session_id)
        if state is None:
            raise ValueError(f"Unknown session_id: {session_id}")
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
            await state.event_publisher.emit(
                MESSAGE_INJECTED,
                turn_id=turn_id,
                actor="worker",
                payload={
                    "kind": "subagent_runtime",
                    "source": "worker",
                    "content": runtime_inject,
                    "label": event.label,
                    "status": event.status,
                    "record_id": event.record_id,
                    "artifact_path": event.artifact_path,
                },
            )
        return messages

    async def _run_resumed_loop(
        self,
        *,
        session_id: str,
        turn_id: str,
        messages: list[dict[str, Any]],
    ) -> tuple[str, Any]:
        """Resume the engine loop once with injected background completions."""
        transport = self._session_transports.get(session_id)
        if transport:
            self._engine._update_tool_contexts(transport.channel, transport.chat_id)
        final_content, meta, _ = await self._engine._execute_loop(
            messages=messages,
            max_iterations=self._engine.max_iterations,
            session_id=session_id,
            turn_id=turn_id,
        )
        return final_content, meta

    async def _finalize_resumed_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        messages: list[dict[str, Any]],
        final_content: str,
        meta: Any,
    ) -> None:
        """Persist resumed output as a durable session turn and emit outbound response."""
        state = self._engine.resume_session(session_id)
        if state is None:
            raise ValueError(f"Unknown session_id: {session_id}")
        transport = self._session_transports.get(session_id)
        channel = transport.channel if transport else "unknown"
        chat_id = transport.chat_id if transport else "unknown"

        resolved_model = self._engine.provider.resolve_model(self._engine.model)
        await _persist_completed_turn(
            engine=self._engine,
            session_id=session_id,
            session_state=state,
            channel=channel,
            chat_id=chat_id,
            messages=messages,
            final_content=final_content,
            meta=meta,
            resolved_model=resolved_model,
        )

        if _is_error_assistant_content(final_content):
            await self._engine._append_session_message_injects(
                session_id,
                [build_error_recovery_inject(final_content)],
            )
            await state.event_publisher.emit(
                TURN_FAILED,
                turn_id=turn_id,
                actor="engine",
                payload={
                    "error": final_content,
                    "iterations": meta.iterations,
                    "tools_used": list(meta.tools_used),
                    "usage": dict(meta.total_usage),
                    "origin": "background_resume",
                },
            )
        else:
            await state.event_publisher.emit(
                ASSISTANT_MESSAGE_COMPLETED,
                turn_id=turn_id,
                actor="engine",
                payload={
                    "content": final_content,
                    "iterations": meta.iterations,
                    "tools_used": list(meta.tools_used),
                    "usage": dict(meta.total_usage),
                    "origin": "background_resume",
                },
            )
            await state.event_publisher.emit(
                TURN_COMPLETED,
                turn_id=turn_id,
                actor="engine",
                payload={
                    "iterations": meta.iterations,
                    "tools_used": list(meta.tools_used),
                    "usage": dict(meta.total_usage),
                    "output_chars": len(final_content),
                    "origin": "background_resume",
                },
            )

        if bool(getattr(self._engine.tools.get("message"), "sent_in_turn", False)):
            return
        if transport is None:
            return
        await self._engine.bus.publish_outbound(
            OutboundMessage(channel=channel, chat_id=chat_id, content=final_content)
        )
