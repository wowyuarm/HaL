"""Main message processing path for AgentEngine."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger

from hal.bus.events import OutboundMessage
from hal.context.compiler import SessionTurnRequest
from hal.context.metrics import (
    USAGE_SOURCE_NONE,
    USAGE_SOURCE_PROVIDER,
    ContextMetrics,
)
from hal.context.token_budget import rough_tokens_from_chars, trim_text_to_token_budget
from hal.context.token_counter import count_messages_tokens
from hal.domain.events import (
    ASSISTANT_MESSAGE_COMPLETED,
    CONTEXT_COMPILED,
    LOOP_STARTED,
    TURN_COMPLETED,
    TURN_FAILED,
    TURN_STARTED,
    USER_MESSAGE,
)
from hal.domain.message_payloads import estimate_content_chars
from hal.domain.session import build_turn_id
from hal.runtime.loop import run_tool_loop
from hal.runtime.session import (
    build_persisted_session_history,
    estimate_messages_request_bytes,
    slim_messages_for_replay,
)

_NO_RESPONSE_GENERATED_MESSAGE = "(No response generated.)"
_ERROR_CALLING_LLM_PREFIX = "Error calling LLM:"


def _message_sent_in_turn(tool: Any) -> bool:
    return bool(getattr(tool, "sent_in_turn", False))


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
    resolved_model: str | None,
    messages: list[dict[str, object]],
    history: list[dict[str, object]],
    search_results: list[object],
    recall_chars: int,
) -> ContextMetrics:
    """Build context metrics snapshot captured before tool-loop execution."""
    history_chars = sum(estimate_content_chars(item.get("content", "")) for item in history)
    recall_max_score = max(
        (float(getattr(result, "score", 0.0)) for result in search_results),
        default=0.0,
    )
    total_input_chars = sum(estimate_content_chars(item.get("content", "")) for item in messages)
    return ContextMetrics(
        timestamp=datetime.now().isoformat(),
        channel=msg.channel,
        chat_id=msg.chat_id,
        mode=mode,
        system_prompt_chars=estimate_content_chars(messages[0].get("content", ""))
        if messages
        else 0,
        history_message_count=len(history),
        history_chars=history_chars,
        recall_count=len(search_results),
        recall_max_score=recall_max_score,
        recall_chars=recall_chars,
        current_message_chars=len(msg.content),
        total_input_chars=total_input_chars,
        estimated_input_tokens=count_messages_tokens(messages, model=resolved_model)
        if resolved_model
        else rough_tokens_from_chars(total_input_chars),
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


def build_direct_inbound_message(
    *, channel: str, chat_id: str, content: str, session_id: str | None = None
) -> object:
    """Build an inbound message object for direct CLI processing."""
    from hal.bus.events import InboundMessage

    return InboundMessage(
        channel=channel,
        sender_id="user",
        chat_id=chat_id,
        content=content,
        session_id=session_id,
    )


def _parse_brief_command(content: str) -> tuple[bool, str]:
    """Parse /brief command. Returns (is_brief, user_prompt)."""
    stripped = content.strip()
    if stripped == "/brief":
        return True, ""
    if stripped.startswith("/brief "):
        return True, stripped[7:].strip()
    return False, ""


def _is_drop_command(content: str) -> bool:
    """Return True when *content* is a ``/drop`` session command."""
    return content.strip() == "/drop"


async def _handle_brief_command(
    *,
    engine: Any,
    session_state: Any,
    channel: str,
    chat_id: str,
    user_prompt: str,
) -> OutboundMessage:
    """Handle /brief: mark session as briefing, start background worker."""
    import asyncio

    session_state.manifest.status = "briefing"
    session_state.brief_task = asyncio.create_task(
        engine._run_session_brief(session_state.session_id, user_prompt=user_prompt)
    )
    engine._clear_session_snapshot(session_state.session_id)

    return OutboundMessage(
        channel=channel,
        chat_id=chat_id,
        content="Starting session brief...",
        metadata={"system_meta": True, "kind": "session_brief_start"},
    )


async def _handle_drop_command(
    *,
    engine: Any,
    session_state: Any,
    channel: str,
    chat_id: str,
) -> OutboundMessage:
    """Handle /drop: end session immediately without running brief worker."""
    await engine.end_session(session_state.session_id, status="dropped", reason="user_drop")

    return OutboundMessage(
        channel=channel,
        chat_id=chat_id,
        content="Session dropped. Next message starts a fresh session.",
        metadata={"system_meta": True, "kind": "session_drop"},
    )


def _record_user_turn(*, engine: Any, msg: Any, session_id: str, session_state: Any) -> None:
    """Persist the inbound user turn and refresh tool context bindings."""
    preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
    logger.info(f"[engine] {msg.channel}:{msg.sender_id}: {preview}")
    engine._mark_threads_touched(session_id, engine._detect_thread_mentions(msg.content))
    engine._update_tool_contexts(msg.channel, msg.chat_id)
    # Propagate session_id to spawn tool for background subagent event routing
    spawn_tool = engine.tools.get("spawn")
    if spawn_tool is not None and hasattr(spawn_tool, "set_session_id"):
        spawn_tool.set_session_id(session_id)


async def _start_turn(*, msg: Any, session_state: Any) -> str:
    """Increment turn counter and emit turn/user events."""
    session_state.manifest.turn_count += 1
    turn_id = build_turn_id(session_state.manifest.turn_count)
    mounted_threads = sorted(session_state.mounted_threads)
    await session_state.event_publisher.emit(
        TURN_STARTED,
        turn_id=turn_id,
        actor="user",
        refs={
            "primary_thread": session_state.primary_thread,
            "mounted_threads": mounted_threads,
        },
        payload={"status": session_state.manifest.status},
    )
    await session_state.event_publisher.emit(
        USER_MESSAGE,
        turn_id=turn_id,
        actor="user",
        payload={
            "content": msg.content,
            "media_count": len(getattr(msg, "media", []) or []),
            "origin": getattr(msg, "origin", "user"),
        },
    )
    return turn_id


async def _record_compiled_context_event(
    *,
    session_state: Any,
    turn_id: str,
    compiled: Any,
    history: list[dict[str, object]],
    estimated_input_tokens: int | None,
) -> None:
    """Persist one context.compiled event for working-log reconstruction."""
    await session_state.event_publisher.emit(
        CONTEXT_COMPILED,
        turn_id=turn_id,
        actor="engine",
        refs={
            "primary_thread": session_state.primary_thread,
            "mounted_threads": sorted(session_state.mounted_threads),
            "recalled_threads": sorted(compiled.recalled_thread_slugs or []),
            "baseline_threads": sorted(compiled.baseline_thread_slugs or []),
        },
        payload={
            "history_messages": len(history),
            "search_results": len(compiled.search_results or []),
            "working_set_messages": len(compiled.messages or []),
            "estimated_input_tokens": estimated_input_tokens,
        },
    )


def _apply_compiled_turn_context(*, engine: Any, session_id: str, compiled: Any) -> None:
    """Track threads discovered during context compilation."""
    if compiled.recalled_thread_slugs:
        engine._mark_threads_touched(session_id, compiled.recalled_thread_slugs)
    if compiled.baseline_thread_slugs:
        engine._mark_threads_touched(session_id, compiled.baseline_thread_slugs)


def _resolve_request_bytes_threshold(engine: Any) -> int:
    session_cfg = getattr(engine._engine_config, "session", None)
    if session_cfg is None:
        return 0
    try:
        return max(int(getattr(session_cfg, "compaction_request_bytes_threshold", 0)), 0)
    except Exception:
        return 0


async def _prepare_messages_for_request(
    *,
    engine: Any,
    msg: Any,
    session_id: str,
    session_state: Any,
    compiled: Any,
    request: SessionTurnRequest,
    resolved_model: str,
) -> Any:
    """Preflight working-set messages against byte budgets before provider fallback trimming."""
    threshold = _resolve_request_bytes_threshold(engine)
    session_cfg = getattr(engine._engine_config, "session", None)
    image_mode = str(getattr(session_cfg, "history_image_replay", "summary") or "summary")
    tool_result_max_bytes = max(int(getattr(session_cfg, "tool_result_replay_max_bytes", 0)), 0)
    tools = engine.tools.get_definitions()

    def _request_bytes(messages: list[dict[str, object]]) -> int:
        return estimate_messages_request_bytes(
            messages,
            model=resolved_model,
            tools=tools,
        )

    messages = compiled.messages
    if threshold <= 0 or _request_bytes(messages) <= threshold:
        return compiled

    slimmed_messages, _ = slim_messages_for_replay(
        messages,
        image_replay_mode=image_mode,
        tool_result_max_bytes=tool_result_max_bytes,
    )
    if _request_bytes(slimmed_messages) <= threshold:
        logger.info("request preflight: slimmed replay payload under byte threshold")
        compiled.messages = slimmed_messages
        return compiled

    compacted_history = await engine._maybe_compact_session_history(
        session_id=session_id,
        history=request.history,
        token_model=resolved_model,
    )
    if compacted_history == request.history:
        compiled.messages = slimmed_messages
        return compiled

    recompacted = await engine.context_compiler.compile_session_turn(
        SessionTurnRequest(
            history=compacted_history,
            current_message=request.current_message,
            media=request.media,
            channel=request.channel,
            chat_id=request.chat_id,
            token_model=request.token_model,
            memory_budget_tokens=request.memory_budget_tokens,
            recall_max_total_tokens=request.recall_max_total_tokens,
            recall_max_per_item_tokens=request.recall_max_per_item_tokens,
            mounted_threads=request.mounted_threads,
        )
    )
    _apply_compiled_turn_context(engine=engine, session_id=session_id, compiled=recompacted)
    recompacted.messages, _ = slim_messages_for_replay(
        recompacted.messages,
        image_replay_mode=image_mode,
        tool_result_max_bytes=tool_result_max_bytes,
    )
    logger.info("request preflight: recompiled turn after byte-aware session compaction")
    return recompacted


async def _persist_completed_turn(
    *,
    engine: Any,
    session_id: str,
    session_state: Any,
    channel: str,
    chat_id: str,
    messages: list[dict[str, object]],
    final_content: str,
    meta: Any,
    resolved_model: str,
) -> bool:
    """Persist session history, assistant output, and snapshot."""
    record_assistant_history = _should_record_assistant_history(final_content)
    if meta.tools_used:
        engine._mark_threads_touched(
            session_id,
            session_state.mounted_threads,
        )

    session_history = build_persisted_session_history(
        working_set_messages=messages,
        final_content=final_content,
        include_final_assistant=record_assistant_history,
    )
    session_history = await engine._maybe_compact_session_history(
        session_id=session_id,
        history=session_history,
        token_model=resolved_model,
    )
    engine._set_session_history(session_id, session_history)
    engine._touch_session(session_id)

    snapshot_messages = engine._build_session_snapshot_messages(
        session_id=session_id,
        token_model=resolved_model,
    )
    engine._store_session_snapshot(
        session_id=session_id,
        messages=snapshot_messages,
        final_content=None,
    )

    return record_assistant_history


async def process_message(engine: Any, msg: Any, mode: str) -> OutboundMessage | None:
    """Process a user message end-to-end."""
    session_state = engine._ensure_session_for_inbound(msg)
    session_id = session_state.session_id
    route = engine._get_session_route(session_id)
    channel = route[0] if route else msg.channel
    chat_id = route[1] if route else msg.chat_id

    with logger.contextualize(session=session_id):
        # /brief command — start background brief worker and end session
        is_brief, brief_prompt = _parse_brief_command(msg.content)
        if is_brief:
            _record_user_turn(
                engine=engine, msg=msg, session_id=session_id, session_state=session_state
            )
            await _start_turn(msg=msg, session_state=session_state)
            return await _handle_brief_command(
                engine=engine,
                session_state=session_state,
                channel=channel,
                chat_id=chat_id,
                user_prompt=brief_prompt,
            )

        # /drop command — end session immediately without briefing
        if _is_drop_command(msg.content):
            _record_user_turn(
                engine=engine, msg=msg, session_id=session_id, session_state=session_state
            )
            await _start_turn(msg=msg, session_state=session_state)
            return await _handle_drop_command(
                engine=engine, session_state=session_state, channel=channel, chat_id=chat_id
            )

        _record_user_turn(
            engine=engine, msg=msg, session_id=session_id, session_state=session_state
        )
        turn_id = await _start_turn(msg=msg, session_state=session_state)

        try:
            resolved_model = engine.provider.resolve_model(engine.model)
            hc = engine._history_config
            history = engine._get_session_history(session_id)
            turn_request = SessionTurnRequest(
                history=history,
                current_message=msg.content,
                media=msg.media if msg.media else None,
                channel=channel,
                chat_id=chat_id,
                token_model=resolved_model,
                memory_budget_tokens=(hc.memory_budget_tokens or None),
                recall_max_total_tokens=hc.recall_max_total_tokens,
                recall_max_per_item_tokens=hc.recall_max_per_item_tokens,
                mounted_threads=session_state.mounted_threads or None,
            )
            compiled = await engine.context_compiler.compile_session_turn(turn_request)
            # Track discovered threads
            if compiled.recalled_thread_slugs:
                engine._mark_threads_touched(session_id, compiled.recalled_thread_slugs)
            if compiled.baseline_thread_slugs:
                engine._mark_threads_touched(session_id, compiled.baseline_thread_slugs)

            compiled = await _prepare_messages_for_request(
                engine=engine,
                msg=msg,
                session_id=session_id,
                session_state=session_state,
                compiled=compiled,
                request=turn_request,
                resolved_model=resolved_model,
            )
            messages = compiled.messages
            search_results = compiled.search_results
            recall_chars = _compute_recall_chars(
                search_results=search_results,
                recall_max_per_item_tokens=hc.recall_max_per_item_tokens,
                resolved_model=resolved_model,
            )
            pre_metrics = _build_pre_metrics(
                msg=msg,
                mode=mode,
                resolved_model=resolved_model,
                messages=messages,
                history=history,
                search_results=search_results,
                recall_chars=recall_chars,
            )
            await _record_compiled_context_event(
                session_state=session_state,
                turn_id=turn_id,
                compiled=compiled,
                history=history,
                estimated_input_tokens=pre_metrics.estimated_input_tokens,
            )
            await session_state.event_publisher.emit(
                LOOP_STARTED,
                turn_id=turn_id,
                actor="engine",
                payload={"max_iterations": engine.max_iterations},
            )

            engine._set_session_active(session_id, True)
            try:
                final_content, meta, _injected = await engine._execute_loop(
                    messages,
                    engine.max_iterations,
                    session_id=session_id,
                )
            finally:
                engine._set_session_active(session_id, False)
            _apply_loop_usage_metrics(metrics=pre_metrics, meta=meta)
            engine._record_metrics(pre_metrics)

            final_content = _normalize_final_content(final_content)
            await _persist_completed_turn(
                engine=engine,
                session_id=session_id,
                session_state=session_state,
                channel=channel,
                chat_id=chat_id,
                messages=messages,
                final_content=final_content,
                meta=meta,
                resolved_model=resolved_model,
            )
            await session_state.event_publisher.emit(
                ASSISTANT_MESSAGE_COMPLETED,
                turn_id=turn_id,
                actor="engine",
                payload={
                    "content": final_content,
                    "iterations": meta.iterations,
                    "tools_used": list(meta.tools_used),
                    "usage": dict(meta.total_usage),
                },
            )
            await session_state.event_publisher.emit(
                TURN_COMPLETED,
                turn_id=turn_id,
                actor="engine",
                payload={
                    "iterations": meta.iterations,
                    "tools_used": list(meta.tools_used),
                    "usage": dict(meta.total_usage),
                    "output_chars": len(final_content),
                },
            )

            preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
            logger.info(f"[engine] response: {preview}")

            if _message_sent_in_turn(engine.tools.get("message")):
                logger.info(
                    "[engine] message already sent via message tool, suppressing final outbound"
                )
                return None

            return OutboundMessage(channel=channel, chat_id=chat_id, content=final_content)
        except Exception as exc:
            await session_state.event_publisher.emit(
                TURN_FAILED,
                turn_id=turn_id,
                actor="engine",
                payload={"error": str(exc)},
            )
            raise


# ---------------------------------------------------------------------------
# Tool-loop execution
# ---------------------------------------------------------------------------


async def execute_loop(
    engine: Any,
    *,
    messages: list[dict[str, object]],
    max_iterations: int,
    add_assistant_message_fn: Any,
    add_tool_result_fn: Any,
    session_key: str | None = None,
    channel: str | None = None,
    chat_id: str | None = None,
) -> tuple[str | None, object, list[object]]:
    """Run one LLM tool-calling loop and collect injected follow-up messages."""
    # Deferred import: _EngineLoopHooks lives in hal.runtime.engine.hooks,
    # a sub-package of hal.runtime. Importing at module level would create a
    # circular init chain (hal.runtime -> execution -> engine.__init__ -> hal.runtime).
    from hal.runtime.engine.hooks import _EngineLoopHooks

    hooks = _EngineLoopHooks(
        engine=engine,
        session_key=session_key,
        channel=channel,
        chat_id=chat_id,
    )
    try:
        final_content, meta = await run_tool_loop(
            provider=engine.provider,
            model=engine.model,
            tools=engine.tools,
            messages=messages,
            max_iterations=max_iterations,
            hooks=hooks,
            add_assistant_message=add_assistant_message_fn,
            add_tool_result=add_tool_result_fn,
            llm_retry_attempts=engine._engine_config.llm_retry.attempts,
            llm_retry_base_delay_s=engine._engine_config.llm_retry.base_delay_s,
            llm_retry_max_delay_s=engine._engine_config.llm_retry.max_delay_s,
        )
        return final_content, meta, hooks.injected
    finally:
        hooks.close()
