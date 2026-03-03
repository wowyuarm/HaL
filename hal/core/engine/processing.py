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


def _message_sent_in_turn(tool: Any) -> bool:
    return bool(getattr(tool, "sent_in_turn", False))


async def process_message(engine: Any, msg: Any, mode: str) -> OutboundMessage | None:
    """Process a user message end-to-end."""
    if task := engine._pending_summaries.pop(msg.session_key, None):
        try:
            await asyncio.wait_for(task, timeout=engine._engine_config.summary_barrier_timeout_s)
        except (asyncio.TimeoutError, Exception) as e:
            logger.warning(f"Summary barrier: {e}")

    preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
    logger.info(f"[engine] {msg.channel}:{msg.sender_id}: {preview}")

    engine.memory.record_conversation(
        channel=msg.channel,
        chat_id=msg.chat_id,
        role="user",
        content=msg.content,
    )

    engine._update_tool_contexts(msg.channel, msg.chat_id)

    hc = engine._history_config
    resolved_model = engine.provider.resolve_model(engine.model)
    history = engine.memory.get_conversation_history(
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

    search_results = []
    if engine._memory_search:
        try:
            search_results = await engine._memory_search.search(
                msg.content,
                top_k=engine._auto_inject_top_k,
                min_score=engine._recall_min_score,
            )
        except Exception as e:
            logger.warning(f"Memory search prefetch failed: {e}")

    messages = engine.context.build_messages(
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
    history_chars = sum(_content_char_len(h.get("content", "")) for h in history)
    recall_max_score = max((float(getattr(r, "score", 0.0)) for r in search_results), default=0.0)
    recall_chars = sum(
        len(
            trim_text_to_token_budget(
                str(getattr(r, "content", "")),
                hc.recall_max_per_item_tokens,
                model=resolved_model,
            )
        )
        for r in search_results
    )
    total_input_chars = sum(_content_char_len(m.get("content", "")) for m in messages)

    pre_metrics = ContextMetrics(
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
    pre_metrics.prompt_tokens = meta.total_usage.get("prompt_tokens")
    pre_metrics.completion_tokens = meta.total_usage.get("completion_tokens")
    pre_metrics.total_tokens = meta.total_usage.get("total_tokens")
    if (
        pre_metrics.total_tokens is None
        and pre_metrics.prompt_tokens is not None
        and pre_metrics.completion_tokens is not None
    ):
        pre_metrics.total_tokens = pre_metrics.prompt_tokens + pre_metrics.completion_tokens
    pre_metrics.usage_available = any(
        v is not None
        for v in (
            pre_metrics.prompt_tokens,
            pre_metrics.completion_tokens,
            pre_metrics.total_tokens,
        )
    )
    pre_metrics.usage_source = (
        USAGE_SOURCE_PROVIDER if pre_metrics.usage_available else USAGE_SOURCE_NONE
    )
    pre_metrics.loop_iterations = meta.iterations
    pre_metrics.tools_used = list(meta.tools_used)
    pre_metrics.spawn_count = meta.tool_call_counts.get("spawn", 0)
    pre_metrics.has_side_effects = meta.has_side_effects
    engine._record_metrics(pre_metrics)

    if not final_content:
        final_content = "(No response generated.)"

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
        final_content=final_content,
    )

    summary_task = engine._trigger_summary(meta, final_content, msg.channel, msg.chat_id)
    if summary_task:
        engine._pending_summaries[msg.session_key] = summary_task

    preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
    logger.info(f"[engine] response: {preview}")

    if _message_sent_in_turn(engine.tools.get("message")):
        logger.info("[engine] message already sent via message tool, suppressing final outbound")
        return None

    return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=final_content)
