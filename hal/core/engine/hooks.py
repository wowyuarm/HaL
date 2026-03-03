"""Loop hooks adapter for AgentEngine."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from hal.bus.events import (
    InboundMessage,
    MessageInjectEvent,
    OutboundMessage,
    ToolCallEvent,
)
from hal.core.runtime.loop import LoopMetadata

from .progress import _format_progress_message
from .subscribers import _EngineEventSubscribers

if TYPE_CHECKING:
    from . import AgentEngine


class _EngineLoopHooks:
    """Thin adapter that translates loop callbacks into bus events."""

    _REMINDER = (
        "[System Reminder]\n"
        "You are a strategist, not an executor.\n"
        "Is the current direction correct? Is there a better approach?\n"
        "If unsure, pause and reassess or ask the user before continuing.\n"
        "Do not respond to this reminder — it is automatic."
    )

    _REMINDER_INTERVAL = 5
    _INTERRUPT_THRESHOLD = 3

    def __init__(
        self,
        engine: "AgentEngine",
        session_key: str | None,
        channel: str | None,
        chat_id: str | None,
    ) -> None:
        self._engine = engine
        self._session_key = session_key
        self._channel = channel
        self._chat_id = chat_id
        self.injected: list[InboundMessage] = []
        self._buffered_pending: list[InboundMessage] = []
        self._event_subscribers = _EngineEventSubscribers(
            engine=engine,
            session_key=session_key,
            channel=channel,
            chat_id=chat_id,
            reminder_text=self._REMINDER,
            reminder_interval=self._REMINDER_INTERVAL,
            injected_sink=self.injected,
        )

    def close(self) -> None:
        self._event_subscribers.close()

    async def _inject_pending(
        self, messages: list[dict[str, Any]], pending_msgs: list[InboundMessage]
    ) -> None:
        for pending in pending_msgs:
            prefixed = f"[User follow-up while you are working] {pending.content}"
            messages.append({"role": "user", "content": prefixed})
            await self._engine.bus.emit(
                MessageInjectEvent(
                    message=pending,
                    prefixed_content=prefixed,
                    messages=messages,
                    channel=self._channel,
                    chat_id=self._chat_id,
                    session_key=self._session_key,
                )
            )

    async def before_llm_call(self, messages: list[dict[str, Any]], meta: LoopMetadata) -> None:
        if self._buffered_pending:
            await self._inject_pending(messages, self._buffered_pending)
            self._buffered_pending.clear()

        if self._session_key:
            fresh = self._engine._drain_pending_for_session(self._session_key)
            if fresh:
                await self._inject_pending(messages, fresh)

        for reminder in self._event_subscribers.pop_pending_reminders():
            messages.append({"role": "user", "content": reminder.content})

        for injection in self._event_subscribers.pop_pending_subagent_runtime_injections():
            messages.append({"role": "user", "content": injection})

    async def on_tool_result(
        self,
        tool_name: str,
        tool_id: str,
        arguments: dict[str, Any],
        result: str,
        messages: list[dict[str, Any]],
        meta: LoopMetadata,
    ) -> None:
        await self._engine.bus.emit(
            ToolCallEvent(
                tool_name=tool_name,
                tool_id=tool_id,
                arguments=arguments,
                result=result,
                total_tool_calls=meta.total_tool_calls,
                messages=messages,
                channel=self._channel,
                chat_id=self._chat_id,
                session_key=self._session_key,
            )
        )

    async def on_no_tool_calls(
        self,
        messages: list[dict[str, Any]],
        response: Any,
        meta: LoopMetadata,
    ) -> bool:
        pending_injections = self._event_subscribers.pop_pending_subagent_runtime_injections()
        if not pending_injections:
            return False

        messages = self._engine.context.add_assistant_message(
            messages,
            response.content,
            [],
            reasoning_content=response.reasoning_content,
        )
        for injection in pending_injections:
            messages.append({"role": "user", "content": injection})
        return True

    async def on_loop_exhausted(
        self,
        messages: list[dict[str, Any]],
        meta: LoopMetadata,
    ) -> str | None:
        return None

    async def on_tool_calls_start(
        self,
        tool_calls: list[Any],
        assistant_content: str | None,
        meta: LoopMetadata,
    ) -> bool | None:
        if self._session_key:
            fresh = self._engine._drain_pending_for_session(self._session_key)
            self._buffered_pending.extend(fresh)

        if len(self._buffered_pending) >= self._INTERRUPT_THRESHOLD:
            count = len(self._buffered_pending)
            logger.info(
                f"[interrupt] skipping {len(tool_calls)} tool calls: {count} user messages buffered"
            )
            return True

        if not (self._channel and self._chat_id):
            return None

        visible_tool_calls = [tc for tc in tool_calls if getattr(tc, "name", "") != "message"]
        if not visible_tool_calls:
            return None

        text = _format_progress_message(assistant_content, visible_tool_calls)
        if not text:
            return None

        await self._engine.bus.publish_outbound(
            OutboundMessage(
                channel=self._channel,
                chat_id=self._chat_id,
                content=text,
                metadata={"progress": True},
            )
        )
        return None
