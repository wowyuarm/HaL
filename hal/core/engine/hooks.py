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

from .progress import _compose_progress_message, _extract_progress_text, _format_tool_hints
from .subscribers import _EngineEventSubscribers, _init_engine_scope

if TYPE_CHECKING:
    from . import AgentEngine

_PROGRESS_META_FLAG = "progress"
_PROGRESS_META_KIND = "progress_kind"
_PROGRESS_KIND_TEXT = "text"
_PROGRESS_KIND_TOOL_HINTS = "tool_hints"
_PROGRESS_APPEND_MODE = "append_mode"
_PROGRESS_APPEND_MODE_CONCAT = "concat"
_PROGRESS_APPEND_KEY = "append_key"
_PROGRESS_APPEND_RESET = "append_reset"
_PROGRESS_APPEND_SEPARATOR = "append_separator"
_PROGRESS_APPEND_SEPARATOR_NL = "\n"


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
        _init_engine_scope(
            self,
            engine=engine,
            session_key=session_key,
            channel=channel,
            chat_id=chat_id,
        )
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
        self._tool_hint_append_key = self._build_tool_hint_append_key()

    def _build_tool_hint_append_key(self) -> str:
        """Build a stable append key for this loop scope."""
        if self._session_key:
            scope = self._session_key
        elif self._channel and self._chat_id:
            scope = f"{self._channel}:{self._chat_id}"
        else:
            scope = "unknown"
        return f"progress:{scope}:tool_hints"

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

    def _buffer_fresh_pending_messages(self) -> None:
        """Move newly queued session messages into the buffered interrupt queue."""
        if not self._session_key:
            return
        fresh = self._engine._drain_pending_for_session(self._session_key)
        self._buffered_pending.extend(fresh)

    def _should_interrupt_tool_calls(self, tool_calls: list[Any]) -> bool:
        """Return True when buffered user follow-ups should interrupt tool execution."""
        buffered_count = len(self._buffered_pending)
        if buffered_count < self._INTERRUPT_THRESHOLD:
            return False
        logger.info(
            f"[interrupt] skipping {len(tool_calls)} tool calls: {buffered_count} user messages buffered"
        )
        return True

    @staticmethod
    def _visible_tool_calls(tool_calls: list[Any]) -> list[Any]:
        """Filter out non-visible message tool calls from progress hints."""
        return [tool_call for tool_call in tool_calls if getattr(tool_call, "name", "") != "message"]

    def _resolve_progress_emission(
        self,
        *,
        assistant_content: str | None,
        visible_tool_calls: list[Any],
    ) -> tuple[str | None, str, bool, bool]:
        """Resolve progress text/tool-hints content and emission toggles."""
        send_progress, send_tool_hints = self._engine._get_channel_progress_policy(self._channel)
        if not send_progress and not send_tool_hints:
            return None, "", False, False

        progress_text = _extract_progress_text(assistant_content)
        tool_hints = _format_tool_hints(visible_tool_calls)
        emit_progress_text = bool(send_progress and progress_text)
        emit_tool_hints = bool(send_tool_hints and tool_hints)
        return progress_text, tool_hints, emit_progress_text, emit_tool_hints

    async def _publish_progress_text(self, progress_text: str) -> None:
        """Publish assistant progress text to outbound channel."""
        await self._engine.bus.publish_outbound(
            OutboundMessage(
                channel=self._channel,
                chat_id=self._chat_id,
                content=progress_text,
                metadata={
                    _PROGRESS_META_FLAG: True,
                    _PROGRESS_META_KIND: _PROGRESS_KIND_TEXT,
                },
            )
        )

    async def _publish_tool_hints(self, tool_hints: str, *, append_reset: bool) -> None:
        """Publish tool-hint progress message in append mode."""
        hints_text = _compose_progress_message(
            progress_text=None,
            tool_hints=tool_hints,
            send_progress=False,
            send_tool_hints=True,
        )
        if not hints_text:
            return

        await self._engine.bus.publish_outbound(
            OutboundMessage(
                channel=self._channel,
                chat_id=self._chat_id,
                content=hints_text,
                metadata={
                    _PROGRESS_META_FLAG: True,
                    _PROGRESS_META_KIND: _PROGRESS_KIND_TOOL_HINTS,
                    _PROGRESS_APPEND_MODE: _PROGRESS_APPEND_MODE_CONCAT,
                    _PROGRESS_APPEND_KEY: self._tool_hint_append_key,
                    _PROGRESS_APPEND_RESET: append_reset,
                    _PROGRESS_APPEND_SEPARATOR: _PROGRESS_APPEND_SEPARATOR_NL,
                },
            )
        )

    async def on_tool_calls_start(
        self,
        tool_calls: list[Any],
        assistant_content: str | None,
        meta: LoopMetadata,
    ) -> bool | None:
        self._buffer_fresh_pending_messages()
        if self._should_interrupt_tool_calls(tool_calls):
            return True

        if not (self._channel and self._chat_id):
            return None

        visible_tool_calls = self._visible_tool_calls(tool_calls)
        if not visible_tool_calls:
            return None

        progress_text, tool_hints, emit_progress_text, emit_tool_hints = (
            self._resolve_progress_emission(
                assistant_content=assistant_content,
                visible_tool_calls=visible_tool_calls,
            )
        )
        if not emit_progress_text and not emit_tool_hints:
            return None

        if emit_progress_text and progress_text is not None:
            await self._publish_progress_text(progress_text)

        if emit_tool_hints:
            await self._publish_tool_hints(tool_hints, append_reset=emit_progress_text)
        return None
