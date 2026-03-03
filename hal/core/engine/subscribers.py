"""Per-loop event subscribers for AgentEngine."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from loguru import logger

from hal.bus.events import MessageInjectEvent, ReminderEvent, SubagentCompleteEvent, ToolCallEvent

from .subagent_injection import (
    _SUBAGENT_HISTORY_MAX_TOKENS,
    _SUBAGENT_RUNTIME_MAX_TOKENS,
    _build_subagent_injection,
    _split_subagent_tool_result,
)

if TYPE_CHECKING:
    from hal.bus.events import InboundMessage

    from . import AgentEngine


class _EngineEventSubscribers:
    """Per-loop event subscribers that host mutable policy/state."""

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
        self._engine = engine
        self._session_key = session_key
        self._channel = channel
        self._chat_id = chat_id
        self._reminder_text = reminder_text
        self._reminder_interval = reminder_interval
        self._injected_sink = injected_sink
        self._last_reminder_at = 0
        self._pending_reminders: list[ReminderEvent] = []
        self._pending_subagent_runtime_injections: list[str] = []
        self._subscriptions = [
            (ToolCallEvent, self._on_tool_call),
            (ReminderEvent, self._on_reminder),
            (MessageInjectEvent, self._on_message_inject),
            (SubagentCompleteEvent, self._on_subagent_complete),
        ]

        for event_type, handler in self._subscriptions:
            self._engine.bus.subscribe(event_type, handler)

    def close(self) -> None:
        for event_type, handler in self._subscriptions:
            self._engine.bus.unsubscribe(event_type, handler)

    def pop_pending_reminders(self) -> list[ReminderEvent]:
        reminders = list(self._pending_reminders)
        self._pending_reminders.clear()
        return reminders

    def pop_pending_subagent_runtime_injections(self) -> list[str]:
        injections = list(self._pending_subagent_runtime_injections)
        self._pending_subagent_runtime_injections.clear()
        return injections

    def _matches_scope(self, event: object) -> bool:
        event_session = getattr(event, "session_key", None)
        event_channel = getattr(event, "channel", None)
        event_chat_id = getattr(event, "chat_id", None)

        if self._session_key and event_session:
            return event_session == self._session_key
        if self._channel and self._chat_id and event_channel and event_chat_id:
            return event_channel == self._channel and event_chat_id == self._chat_id
        return True

    async def _on_message_inject(self, event: MessageInjectEvent) -> None:
        if not self._matches_scope(event):
            return

        self._injected_sink.append(event.message)
        logger.info(f"[inject] mid-loop message from {event.message.sender_id}")

        if self._channel and self._chat_id:
            self._engine.memory.record_conversation(
                channel=self._channel,
                chat_id=self._chat_id,
                role="user",
                content=event.prefixed_content,
            )

    async def _on_tool_call(self, event: ToolCallEvent) -> None:
        if not self._matches_scope(event):
            return

        if self._channel and self._chat_id:
            self._engine.memory.record_conversation(
                channel=self._channel,
                chat_id=self._chat_id,
                role="tool",
                content=(
                    "Calling "
                    f"{event.tool_name} with arguments: "
                    f"{json.dumps(event.arguments, ensure_ascii=False)}"
                ),
                tool_name=event.tool_name,
                tool_result=event.result,
            )

        total_tool_calls = event.total_tool_calls
        if (
            total_tool_calls > 0
            and total_tool_calls % self._reminder_interval == 0
            and total_tool_calls > self._last_reminder_at
        ):
            self._last_reminder_at = total_tool_calls
            await self._engine.bus.emit(
                ReminderEvent(
                    content=self._reminder_text,
                    total_tool_calls=total_tool_calls,
                    messages=event.messages,
                    channel=event.channel,
                    chat_id=event.chat_id,
                    session_key=event.session_key,
                )
            )

        if event.tool_name != "spawn" or event.arguments.get("background", False):
            return

        label = event.arguments.get("label", event.arguments.get("task", "")[:40])
        parsed = _split_subagent_tool_result(event.result)
        await self._engine.bus.emit(
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

    async def _on_reminder(self, event: ReminderEvent) -> None:
        if not self._matches_scope(event):
            return
        self._pending_reminders.append(event)

    async def _on_subagent_complete(self, event: SubagentCompleteEvent) -> None:
        if not self._matches_scope(event):
            return

        if not event.background:
            return

        logger.info(f"[inject] subagent result: {event.label} ({event.status})")

        runtime_inject = _build_subagent_injection(
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
        self._pending_subagent_runtime_injections.append(runtime_inject)


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

        history_inject = _build_subagent_injection(
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
            max_tokens=_SUBAGENT_HISTORY_MAX_TOKENS,
        )
        self._engine.memory.record_conversation(
            channel=event.channel,
            chat_id=event.chat_id,
            role="user",
            content=history_inject,
            entry_type="injection",
        )
        await self._engine.queue_background_completion(event)
