"""Main message processing path for AgentEngine."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from loguru import logger

from hal.bus.events import OutboundMessage
from hal.core.context.metrics import (
    USAGE_SOURCE_NONE,
    USAGE_SOURCE_PROVIDER,
    ContextMetrics,
)
from hal.core.context.token_budget import rough_tokens_from_chars, trim_text_to_token_budget

from .inspect import _content_char_len

_NO_RESPONSE_GENERATED_MESSAGE = "(No response generated.)"
_ERROR_CALLING_LLM_PREFIX = "Error calling LLM:"


def _message_sent_in_turn(tool: Any) -> bool:
    return bool(getattr(tool, "sent_in_turn", False))


async def _await_summary_barrier(*, engine: Any, msg: Any) -> None:
    """Await pending summary task for this session before handling a new message."""
    task = engine._pending_summaries.pop(msg.session_key, None)
    if task is None:
        return
    try:
        await asyncio.wait_for(task, timeout=engine._engine_config.summary_barrier_timeout_s)
    except (asyncio.TimeoutError, Exception) as e:
        logger.warning(f"Summary barrier: {e}")


def _load_conversation_history(
    *, engine: Any, msg: Any, resolved_model: str
) -> list[dict[str, object]]:
    """Load bounded conversation history for prompt assembly."""
    hc = engine._history_config
    return engine.memory.get_conversation_history(
        channel=msg.channel,
        chat_id=msg.chat_id,
        max_messages=hc.max_messages,
        include_tools=False,
        recent_full_turns=hc.recent_full_turns,
        assistant_truncate_tokens=hc.assistant_truncate_tokens,
        max_tokens=hc.max_history_tokens,
        history_days=hc.history_days,
        token_model=resolved_model,
    )


async def _prefetch_memory_results(*, engine: Any, msg: Any) -> list[object]:
    """Best-effort memory-search prefetch for auto-injection."""
    if not engine._memory_search:
        return []
    try:
        return await engine._memory_search.search(
            msg.content,
            top_k=engine._auto_inject_top_k,
            min_score=engine._recall_min_score,
        )
    except Exception as e:
        logger.warning(f"Memory search prefetch failed: {e}")
        return []


def _build_context_messages(
    *,
    engine: Any,
    msg: Any,
    history: list[dict[str, object]],
    search_results: list[object],
    resolved_model: str,
) -> list[dict[str, object]]:
    """Build final message list for the LLM loop."""
    hc = engine._history_config
    return engine.context.build_messages(
        history=history,
        current_message=msg.content,
        media=msg.media if msg.media else None,
        channel=msg.channel,
        chat_id=msg.chat_id,
        memory_search_results=search_results or None,
        memory_budget_tokens=(hc.memory_budget_tokens or None),
        recall_max_total_tokens=hc.recall_max_total_tokens,
        recall_max_per_item_tokens=hc.recall_max_per_item_tokens,
        token_model=resolved_model,
    )


def _compute_recall_chars(
    *,
    search_results: list[object],
    recall_max_per_item_tokens: int,
    resolved_model: str,
) -> int:
    return sum(
        len(
            trim_text_to_token_budget(
                str(getattr(result, "content", "")),
                recall_max_per_item_tokens,
                model=resolved_model,
            )
        )
        for result in search_results
    )


def _build_pre_metrics(
    *,
    msg: Any,
    mode: str,
    messages: list[dict[str, object]],
    history: list[dict[str, object]],
    search_results: list[object],
    recall_chars: int,
) -> ContextMetrics:
    """Build context metrics snapshot captured before tool-loop execution."""
    history_chars = sum(_content_char_len(item.get("content", "")) for item in history)
    recall_max_score = max(
        (float(getattr(result, "score", 0.0)) for result in search_results),
        default=0.0,
    )
    total_input_chars = sum(_content_char_len(item.get("content", "")) for item in messages)
    return ContextMetrics(
        timestamp=datetime.now().isoformat(),
        channel=msg.channel,
        chat_id=msg.chat_id,
        mode=mode,
        system_prompt_chars=_content_char_len(messages[0].get("content", "")) if messages else 0,
        history_message_count=len(history),
        history_chars=history_chars,
        recall_count=len(search_results),
        recall_max_score=recall_max_score,
        recall_chars=recall_chars,
        current_message_chars=len(msg.content),
        total_input_chars=total_input_chars,
        estimated_input_tokens=rough_tokens_from_chars(total_input_chars),
    )


def _apply_loop_usage_metrics(*, metrics: ContextMetrics, meta: object) -> None:
    """Map loop usage/tool metadata onto context metrics."""
    metrics.prompt_tokens = meta.total_usage.get("prompt_tokens")
    metrics.completion_tokens = meta.total_usage.get("completion_tokens")
    metrics.total_tokens = meta.total_usage.get("total_tokens")
    if (
        metrics.total_tokens is None
        and metrics.prompt_tokens is not None
        and metrics.completion_tokens is not None
    ):
        metrics.total_tokens = metrics.prompt_tokens + metrics.completion_tokens
    metrics.usage_available = any(
        value is not None
        for value in (
            metrics.prompt_tokens,
            metrics.completion_tokens,
            metrics.total_tokens,
        )
    )
    metrics.usage_source = USAGE_SOURCE_PROVIDER if metrics.usage_available else USAGE_SOURCE_NONE
    metrics.loop_iterations = meta.iterations
    metrics.tools_used = list(meta.tools_used)
    metrics.spawn_count = meta.tool_call_counts.get("spawn", 0)
    metrics.has_side_effects = meta.has_side_effects


def _normalize_final_content(final_content: str | None) -> str:
    if final_content:
        return final_content
    return _NO_RESPONSE_GENERATED_MESSAGE


def _should_record_assistant_history(content: str) -> bool:
    """Return True when assistant content should be persisted into history."""
    normalized = content.strip()
    if not normalized:
        return False
    if normalized == _NO_RESPONSE_GENERATED_MESSAGE:
        return False
    if normalized.startswith(_ERROR_CALLING_LLM_PREFIX):
        return False
    return True


def build_engine_error_response(*, msg: Any, error: Exception) -> OutboundMessage:
    """Build a user-facing fallback response for engine-loop exceptions."""
    return OutboundMessage(
        channel=msg.channel,
        chat_id=msg.chat_id,
        content=f"Sorry, I encountered an error: {str(error)}",
    )


def build_direct_inbound_message(*, channel: str, chat_id: str, content: str) -> object:
    """Build an inbound message object for direct CLI processing."""
    from hal.bus.events import InboundMessage

    return InboundMessage(channel=channel, sender_id="user", chat_id=chat_id, content=content)


async def process_message(engine: Any, msg: Any, mode: str) -> OutboundMessage | None:
    """Process a user message end-to-end."""
    await _await_summary_barrier(engine=engine, msg=msg)

    preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
    logger.info(f"[engine] {msg.channel}:{msg.sender_id}: {preview}")

    engine.memory.record_conversation(
        channel=msg.channel,
        chat_id=msg.chat_id,
        role="user",
        content=msg.content,
    )

    engine._update_tool_contexts(msg.channel, msg.chat_id)

    resolved_model = engine.provider.resolve_model(engine.model)
    hc = engine._history_config
    history = _load_conversation_history(engine=engine, msg=msg, resolved_model=resolved_model)
    search_results = await _prefetch_memory_results(engine=engine, msg=msg)
    messages = _build_context_messages(
        engine=engine,
        msg=msg,
        history=history,
        search_results=search_results,
        resolved_model=resolved_model,
    )
    recall_chars = _compute_recall_chars(
        search_results=search_results,
        recall_max_per_item_tokens=hc.recall_max_per_item_tokens,
        resolved_model=resolved_model,
    )
    pre_metrics = _build_pre_metrics(
        msg=msg,
        mode=mode,
        messages=messages,
        history=history,
        search_results=search_results,
        recall_chars=recall_chars,
    )

    engine._set_session_active(msg.session_key, True)
    try:
        final_content, meta, _injected = await engine._execute_loop(
            messages,
            engine.max_iterations,
            session_key=msg.session_key,
            channel=msg.channel,
            chat_id=msg.chat_id,
        )
    finally:
        engine._set_session_active(msg.session_key, False)
    _apply_loop_usage_metrics(metrics=pre_metrics, meta=meta)
    engine._record_metrics(pre_metrics)

    final_content = _normalize_final_content(final_content)
    record_assistant_history = _should_record_assistant_history(final_content)

    if record_assistant_history:
        engine.memory.record_conversation(
            channel=msg.channel,
            chat_id=msg.chat_id,
            role="assistant",
            content=final_content,
        )
    engine._store_session_snapshot(
        session_key=msg.session_key,
        channel=msg.channel,
        chat_id=msg.chat_id,
        messages=messages,
        final_content=final_content if record_assistant_history else None,
    )

    summary_task = None
    if record_assistant_history:
        summary_task = engine._trigger_summary(meta, final_content, msg.channel, msg.chat_id)
    if summary_task:
        engine._pending_summaries[msg.session_key] = summary_task

    preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
    logger.info(f"[engine] response: {preview}")

    if _message_sent_in_turn(engine.tools.get("message")):
        logger.info("[engine] message already sent via message tool, suppressing final outbound")
        return None

    return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=final_content)
