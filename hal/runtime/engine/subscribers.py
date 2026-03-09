"""Per-loop event subscribers for AgentEngine."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from hal.bus.events import MessageInjectEvent, ReminderEvent, SubagentCompleteEvent, ToolCallEvent
from hal.context.token_budget import trim_text_to_token_budget
from hal.runtime.brief import extract_touched_threads

from .subagent_injection import (
    _SUBAGENT_RUNTIME_MAX_TOKENS,
    _build_subagent_injection,
    _split_subagent_tool_result,
)

_TOOL_RESULT_PREVIEW_TOKENS = 300

if TYPE_CHECKING:
    from hal.bus.events import InboundMessage

    from . import AgentEngine


def _init_engine_scope(
    target: object,
    *,
    engine: "AgentEngine",
    session_key: str | None,
    channel: str | None,
    chat_id: str | None,
) -> None:
    """Initialize common scope attributes shared by loop helpers/subscribers."""
    target._engine = engine  # type: ignore[attr-defined]
    target._session_key = session_key  # type: ignore[attr-defined]
    target._channel = channel  # type: ignore[attr-defined]
    target._chat_id = chat_id  # type: ignore[attr-defined]


class _EngineEventSubscribers:
    """Facade over per-loop event subscribers grouped by event responsibility."""

    def __init__(
        self,
        *,
        engine: "AgentEngine",
        session_key: str | None,
        channel: str | None,
        chat_id: str | None,
        reminder_text: str,
        reminder_interval: int,
        injected_sink: list["InboundMessage"],
    ) -> None:
        scope = _SubscriberScope(
            engine=engine,
            session_key=session_key,
            channel=channel,
            chat_id=chat_id,
        )
        self._message_inject = _MessageInjectSubscriber(scope=scope, injected_sink=injected_sink)
        self._tool_call = _ToolCallSubscriber(
            scope=scope,
            reminder_text=reminder_text,
            reminder_interval=reminder_interval,
        )
        self._reminder = _ReminderQueueSubscriber(scope=scope)
        self._subagent_runtime = _SubagentRuntimeSubscriber(scope=scope)

    def close(self) -> None:
        self._message_inject.close()
        self._tool_call.close()
        self._reminder.close()
        self._subagent_runtime.close()

    def pop_pending_reminders(self) -> list[ReminderEvent]:
        return self._reminder.pop_pending()

    def pop_pending_subagent_runtime_injections(self) -> list[str]:
        return self._subagent_runtime.pop_pending()


class _SubscriberScope:
    """Shared scope container for per-loop event subscribers."""

    def __init__(
        self,
        *,
        engine: "AgentEngine",
        session_key: str | None,
        channel: str | None,
        chat_id: str | None,
    ) -> None:
        self.engine = engine
        self.session_key = session_key
        self.channel = channel
        self.chat_id = chat_id

    def _matches_scope(self, event: object) -> bool:
        event_session = getattr(event, "session_key", None)
        event_channel = getattr(event, "channel", None)
        event_chat_id = getattr(event, "chat_id", None)

        if self.session_key and event_session:
            return event_session == self.session_key
        if self.channel and self.chat_id and event_channel and event_chat_id:
            return event_channel == self.channel and event_chat_id == self.chat_id
        return True


class _ScopedPendingSubscriber:
    """Base subscriber with one pending queue and one subscribed event type."""

    def __init__(
        self,
        *,
        scope: _SubscriberScope,
        event_type: type[Any],
        handler: Any,
    ) -> None:
        self._scope = scope
        self._event_type = event_type
        self._handler = handler
        self._pending_items: list[Any] = []
        self._scope.engine.bus.subscribe(event_type, handler)

    def close(self) -> None:
        self._scope.engine.bus.unsubscribe(self._event_type, self._handler)

    def pop_pending(self) -> list[Any]:
        items = list(self._pending_items)
        self._pending_items.clear()
        return items


class _QueuedScopedSubscriber(_ScopedPendingSubscriber):
    """Template for scope-filtered subscribers that enqueue derived items."""

    EVENT_TYPE: type[Any]

    def __init__(self, *, scope: _SubscriberScope) -> None:
        super().__init__(scope=scope, event_type=self.EVENT_TYPE, handler=self._on_event)

    async def _on_event(self, event: Any) -> None:
        if not self._scope._matches_scope(event):
            return
        pending_item = self._build_pending_item(event)
        if pending_item is not None:
            self._pending_items.append(pending_item)

    def _build_pending_item(self, event: Any) -> Any | None:
        raise NotImplementedError


class _MessageInjectSubscriber:
    """Handle mid-loop message injection events for one loop scope."""

    def __init__(self, *, scope: _SubscriberScope, injected_sink: list["InboundMessage"]) -> None:
        self._scope = scope
        self._injected_sink = injected_sink
        self._scope.engine.bus.subscribe(MessageInjectEvent, self._on_message_inject)

    def close(self) -> None:
        self._scope.engine.bus.unsubscribe(MessageInjectEvent, self._on_message_inject)

    async def _on_message_inject(self, event: MessageInjectEvent) -> None:
        if not self._scope._matches_scope(event):
            return

        self._injected_sink.append(event.message)
        logger.info(f"[inject] mid-loop message from {event.message.sender_id}")


class _ToolCallSubscriber:
    """Handle tool-call side effects for one loop scope."""

    def __init__(
        self,
        *,
        scope: _SubscriberScope,
        reminder_text: str,
        reminder_interval: int,
    ) -> None:
        self._scope = scope
        self._reminder_text = reminder_text
        self._reminder_interval = reminder_interval
        self._last_reminder_at = 0
        self._scope.engine.bus.subscribe(ToolCallEvent, self._on_tool_call)

    def close(self) -> None:
        self._scope.engine.bus.unsubscribe(ToolCallEvent, self._on_tool_call)

    async def _on_tool_call(self, event: ToolCallEvent) -> None:
        if not self._scope._matches_scope(event):
            return

        self._mark_touched_threads(event)
        self._record_tool_call_event(event)
        await self._maybe_emit_reminder(event)
        await self._maybe_emit_inline_subagent_completion(event)

    def _mark_touched_threads(self, event: ToolCallEvent) -> None:
        if not event.session_key or event.tool_name != "fs":
            return
        touched = extract_touched_threads(event.arguments)
        if touched:
            self._scope.engine._mark_threads_touched(event.session_key, touched)

    def _record_tool_call_event(self, event: ToolCallEvent) -> None:
        if not event.session_key:
            return
        session_id = self._scope.engine._get_session_id(event.session_key)
        if not session_id:
            return
        result_text = event.result or ""
        result_preview = (
            trim_text_to_token_budget(
                result_text, _TOOL_RESULT_PREVIEW_TOKENS, suffix="...[truncated]"
            )
            if result_text
            else ""
        )
        self._scope.engine.memory.record_event(
            session_id=session_id,
            event_type="tool_call",
            channel=event.channel,
            chat_id=event.chat_id,
            payload={
                "tool": event.tool_name,
                "args": event.arguments,
                "result_size": len(result_text),
                "result_preview": result_preview,
            },
        )

    async def _maybe_emit_reminder(self, event: ToolCallEvent) -> None:
        total_tool_calls = event.total_tool_calls
        if not self._should_emit_reminder(total_tool_calls):
            return
        self._last_reminder_at = total_tool_calls
        await self._scope.engine.bus.emit(
            ReminderEvent(
                content=self._reminder_text,
                total_tool_calls=total_tool_calls,
                messages=event.messages,
                channel=event.channel,
                chat_id=event.chat_id,
                session_key=event.session_key,
            )
        )

    def _should_emit_reminder(self, total_tool_calls: int) -> bool:
        return (
            total_tool_calls > 0
            and total_tool_calls % self._reminder_interval == 0
            and total_tool_calls > self._last_reminder_at
        )

    async def _maybe_emit_inline_subagent_completion(self, event: ToolCallEvent) -> None:
        if event.tool_name != "spawn" or event.arguments.get("background", False):
            return

        label = event.arguments.get("label", event.arguments.get("task", "")[:40])
        parsed = _split_subagent_tool_result(event.result)
        await self._scope.engine.bus.emit(
            SubagentCompleteEvent(
                label=label,
                status=parsed.status,
                content=parsed.content,
                background=False,
                messages=event.messages,
                channel=event.channel,
                chat_id=event.chat_id,
                session_key=event.session_key,
                record_id=parsed.record_id,
                artifact_path=parsed.artifact_path,
                total_tokens=parsed.total_tokens,
                tools_used=parsed.tools_used,
                tool_call_counts=parsed.tool_call_counts,
                has_side_effects=parsed.has_side_effects,
                files_modified=parsed.files_modified,
                commands_run=parsed.commands_run,
                tool_errors=parsed.tool_errors,
                missing_artifacts=parsed.missing_artifacts,
            )
        )


class _ReminderQueueSubscriber(_QueuedScopedSubscriber):
    """Collect reminder events for later injection into the working set."""

    EVENT_TYPE = ReminderEvent

    def _build_pending_item(self, event: ReminderEvent) -> ReminderEvent:
        return event


class _SubagentRuntimeSubscriber(_QueuedScopedSubscriber):
    """Collect background subagent completions for later runtime injection."""

    EVENT_TYPE = SubagentCompleteEvent

    def _build_pending_item(self, event: SubagentCompleteEvent) -> str | None:
        if not event.background:
            return None
        logger.info(f"[inject] subagent result: {event.label} ({event.status})")
        return _build_subagent_injection(
            label=event.label,
            content=event.content,
            status=event.status,
            background=event.background,
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


class _EngineBackgroundSubscribers:
    """Long-lived event subscribers that persist subagent completion history."""

    def __init__(self, *, engine: "AgentEngine") -> None:
        self._engine = engine
        self._engine.bus.subscribe(SubagentCompleteEvent, self._on_subagent_complete)

    def close(self) -> None:
        self._engine.bus.unsubscribe(SubagentCompleteEvent, self._on_subagent_complete)

    async def _on_subagent_complete(self, event: SubagentCompleteEvent) -> None:
        if not (event.channel and event.chat_id):
            return

        if event.session_key:
            session_id = self._engine._get_session_id(event.session_key)
            if session_id:
                self._engine.memory.record_event(
                    session_id=session_id,
                    event_type="subagent_complete",
                    channel=event.channel,
                    chat_id=event.chat_id,
                    payload={
                        "record_id": event.record_id,
                        "label": event.label,
                        "status": event.status,
                        "artifact_path": event.artifact_path,
                    },
                )

        await self._engine.queue_background_completion(event)
