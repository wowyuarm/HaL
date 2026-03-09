"""Loop hooks adapter for AgentEngine."""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Iterable

from loguru import logger

from hal.bus.events import (
    InboundMessage,
    MessageInjectEvent,
    OutboundMessage,
    ToolCallEvent,
)
from hal.context.message_building import add_assistant_message as append_assistant_message
from hal.runtime.engine.context_advisor import (
    build_context_advisor_input,
    build_context_hint_keys,
    build_context_hint_text,
    build_thread_path_map,
    filter_context_advisor_suggestion,
    has_substantive_tool_calls,
    request_context_advisor_suggestion,
)
from hal.runtime.loop import LoopMetadata

from .subscribers import _EngineEventSubscribers, _init_engine_scope

if TYPE_CHECKING:
    from . import AgentEngine


# ---------------------------------------------------------------------------
# Progress message formatting helpers
# ---------------------------------------------------------------------------

_THINK_RE = re.compile(r"<think>.*?</think>|<think>.*$", re.DOTALL)


def _extract_progress_text(
    assistant_content: str | None,
) -> str | None:
    """Extract a clean assistant intent line for interim progress display."""
    if not assistant_content:
        return None

    cleaned = _THINK_RE.sub("", assistant_content).strip()
    return cleaned or None


def _format_tool_hints(tool_calls: list[Any]) -> list[str]:
    """Format tool-call hints for interim progress display."""
    hints: list[str] = []
    for tc in tool_calls or []:
        summary = _summarize_args(tc.arguments)
        hints.append(f"\u21b3 {tc.name}({summary})")
    return hints


def _compose_progress_message(
    progress_text: str | None,
    tool_hints: list[str],
    *,
    send_progress: bool,
    send_tool_hints: bool,
) -> str | None:
    """Compose the interim progress message according to channel policy."""
    parts: list[str] = []
    if send_progress and progress_text:
        parts.append(progress_text)
    if send_tool_hints and tool_hints:
        parts.extend(tool_hints)
    return "\n".join(parts) if parts else None


def _summarize_args(args: dict[str, Any] | None) -> str:
    """Produce a short argument summary for progress display."""
    if not args:
        return ""

    for key in ("query", "task", "command", "path", "url", "content", "pattern"):
        if key in args:
            val = str(args[key])
            if len(val) > 60:
                val = val[:57] + "..."
            return repr(val)

    first_val = str(next(iter(args.values())))
    if len(first_val) > 60:
        first_val = first_val[:57] + "..."
    return repr(first_val)


# ---------------------------------------------------------------------------
# Hook constants
# ---------------------------------------------------------------------------

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
        "Step back. Is the current direction correct? Is there a better approach?\n"
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
        self._pending_context_hints: list[str] = []
        self._latest_user_message: str = ""
        self._advisor_task: asyncio.Task[str | None] | None = None
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
        if self._advisor_task and not self._advisor_task.done():
            self._advisor_task.cancel()
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
        self._latest_user_message = self._extract_latest_user_content(messages)
        self._collect_completed_context_hint()
        await self._inject_buffered_pending(messages)
        await self._inject_fresh_pending(messages)
        self._append_pending_reminders(messages)
        self._append_pending_subagent_runtime_injections(messages)
        self._flush_context_hints(messages)

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

        messages = append_assistant_message(
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

    def _extract_latest_user_content(self, messages: list[dict[str, Any]]) -> str:
        """Return latest user text content from current message list."""
        for message in reversed(messages):
            if message.get("role") != "user":
                continue
            content = message.get("content")
            if isinstance(content, str):
                return content
            return str(content)
        return ""

    def _collect_completed_context_hint(self) -> None:
        """Move one finished advisor result into the pending hint buffer."""
        if not self._advisor_task or not self._advisor_task.done():
            return
        try:
            hint = self._advisor_task.result()
        except Exception as e:
            logger.warning(f"Context advisor failed: {e}")
            hint = None
        self._advisor_task = None
        if hint:
            self._pending_context_hints.append(hint)

    async def _inject_buffered_pending(self, messages: list[dict[str, Any]]) -> None:
        """Inject follow-up user messages buffered during tool execution."""
        if not self._buffered_pending:
            return
        await self._inject_pending(messages, self._buffered_pending)
        self._buffered_pending.clear()

    async def _inject_fresh_pending(self, messages: list[dict[str, Any]]) -> None:
        """Inject newly queued session messages before the next LLM call."""
        if not self._session_key:
            return
        fresh = self._engine._drain_pending_for_session(self._session_key)
        if fresh:
            await self._inject_pending(messages, fresh)

    def _append_pending_reminders(self, messages: list[dict[str, Any]]) -> None:
        """Append reminder events as synthetic user messages."""
        self._append_user_messages(
            messages,
            [reminder.content for reminder in self._event_subscribers.pop_pending_reminders()],
        )

    def _append_pending_subagent_runtime_injections(self, messages: list[dict[str, Any]]) -> None:
        """Append runtime subagent injections before the next LLM call."""
        self._append_user_messages(
            messages,
            self._event_subscribers.pop_pending_subagent_runtime_injections(),
        )

    def _flush_context_hints(self, messages: list[dict[str, Any]]) -> None:
        """Append buffered context hints as user messages."""
        if not self._pending_context_hints:
            return
        for hint in self._pending_context_hints:
            messages.append({"role": "user", "content": hint})
        self._pending_context_hints.clear()

    @staticmethod
    def _append_user_messages(messages: list[dict[str, Any]], contents: Iterable[str]) -> None:
        """Append multiple user-role text messages in order."""
        for content in contents:
            messages.append({"role": "user", "content": content})

    def _maybe_start_context_advisor(
        self,
        *,
        tool_calls: list[Any],
        assistant_content: str | None,
    ) -> None:
        """Start non-blocking advisor task per loop on substantive tool usage."""
        if not self._session_key:
            return
        if not self._engine._engine_config.context_advisor_enabled:
            return
        if self._advisor_task is not None and not self._advisor_task.done():
            return
        if not has_substantive_tool_calls(tool_calls):
            return

        self._advisor_task = asyncio.create_task(
            self._run_context_advisor(
                tool_calls=tool_calls,
                assistant_content=assistant_content,
            )
        )

    async def _run_context_advisor(
        self,
        *,
        tool_calls: list[Any],
        assistant_content: str | None,
    ) -> str | None:
        """Call worker model to produce optional skill/thread hint."""
        chat, model = self._resolve_context_advisor_client()
        if chat is None:
            return None

        skill_registry = self._engine.context_registry.skill_snapshot()
        thread_registry = self._engine.context_registry.thread_snapshot()
        advisor_input = build_context_advisor_input(
            latest_user_message=self._latest_user_message,
            assistant_content=assistant_content,
            tool_calls=tool_calls,
            skill_registry=skill_registry,
            thread_registry=thread_registry,
        )

        try:
            suggestion = await request_context_advisor_suggestion(
                chat=chat,
                model=model,
                advisor_input=advisor_input,
            )
        except Exception as e:
            logger.warning(f"Context advisor request failed: {e}")
            return None

        if suggestion is None:
            return None

        # Deduplicate hints within a session scope.
        keys = build_context_hint_keys(suggestion)
        new_keys = self._engine._filter_new_context_hint_keys(self._session_key, keys)
        if not new_keys:
            return None

        filtered = filter_context_advisor_suggestion(suggestion, allowed_keys=new_keys)
        if filtered is None:
            return None

        if filtered.threads and self._session_key:
            touched = self._engine.context_registry.expand_related_thread_slugs(
                set(filtered.threads)
            )
            self._engine._mark_threads_touched(self._session_key, touched)

        return build_context_hint_text(
            filtered,
            thread_path_map=build_thread_path_map(thread_registry),
        )

    def _resolve_context_advisor_client(
        self,
    ) -> tuple[Callable[..., Awaitable[Any]] | None, str | None]:
        """Resolve the worker-model chat callable used by the advisor."""
        provider = getattr(self._engine.subagents, "provider", None)
        model = getattr(self._engine.subagents, "model", None)
        chat = getattr(provider, "chat", None)
        return (chat if callable(chat) else None, model)

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
        return [
            tool_call for tool_call in tool_calls if getattr(tool_call, "name", "") != "message"
        ]

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
        self._maybe_start_context_advisor(
            tool_calls=tool_calls,
            assistant_content=assistant_content,
        )
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
