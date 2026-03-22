"""Context inspection builders for AgentEngine debug output."""

from __future__ import annotations

from typing import Any

from hal.context.compiler import ContextCompiler, SessionTurnRequest
from hal.context.token_counter import (
    count_message_tokens,
    count_messages_tokens,
    count_prompt_tokens,
    rough_tokens_from_chars,
)
from hal.domain.message_payloads import estimate_content_chars


def _compiled_scope_thread_slugs(compiled: Any) -> list[str]:
    scope_threads = getattr(compiled, "scope_thread_slugs", None)
    return sorted(str(slug) for slug in (scope_threads or set()) if str(slug))


def _compiled_injected_messages(compiled: Any) -> list[Any]:
    return list(getattr(compiled, "injected_messages", None) or [])


def _estimate_messages_tokens(model: str, messages: list[dict[str, Any]]) -> int:
    """Estimate token count for a list of messages."""
    return count_messages_tokens(messages, model=model)


def _estimate_per_message_tokens(model: str, messages: list[dict[str, Any]]) -> list[int]:
    """Estimate token count for each message (for context inspector display)."""
    return [count_message_tokens(message, model=model) for message in messages]


def _estimate_prompt_tokens(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> dict[str, Any]:
    """Estimate input token usage for context inspection output."""
    return count_prompt_tokens(messages=messages, tools=tools, model=model)


async def build_context_inspection(
    *,
    provider: Any,
    model: str,
    memory: Any,
    context_builder: Any,
    context_registry: Any,
    tools_registry: Any,
    recall_index: Any,
    auto_inject_top_k: int,
    recall_min_score: float,
    history_config: Any,
    channel: str,
    chat_id: str,
    session_id: str | None = None,
    session_history: list[dict[str, object]] | None = None,
    mounted_threads: set[str] | None = None,
    current_message: str,
    mode: str,
) -> dict[str, Any]:
    """Build inspect_context payload without mutating memory state."""
    hc = history_config
    resolved_model = provider.resolve_model(model)
    history = list(session_history) if session_history is not None else []

    compiler = ContextCompiler(
        context_builder=context_builder,
        context_registry=context_registry,
        recall_index=recall_index,
        auto_inject_top_k=auto_inject_top_k,
        recall_min_score=recall_min_score,
    )
    compiled = await compiler.compile_session_turn(
        SessionTurnRequest(
            history=history,
            current_message=current_message,
            media=None,
            channel=channel,
            chat_id=chat_id,
            token_model=resolved_model,
            memory_budget_tokens=(hc.memory_budget_tokens or None),
            recall_max_total_tokens=hc.recall_max_total_tokens,
            recall_max_per_item_tokens=hc.recall_max_per_item_tokens,
            mounted_threads=mounted_threads,
        )
    )
    messages = compiled.messages
    search_results = compiled.search_results

    tools = tools_registry.get_definitions()
    token_estimate = _estimate_prompt_tokens(resolved_model, messages, tools)
    history_tokens = _estimate_messages_tokens(resolved_model, history)
    system_prompt_tokens = _estimate_messages_tokens(resolved_model, messages[:1])
    per_message_tokens = _estimate_per_message_tokens(resolved_model, messages)

    seen_recall: set[tuple[str, str, str]] = set()
    recall_items: list[dict[str, Any]] = []
    for r in search_results:
        key = (
            getattr(r, "source", ""),
            getattr(r, "heading", ""),
            getattr(r, "source_type", "raw"),
        )
        if key in seen_recall:
            continue
        seen_recall.add(key)
        recall_items.append(
            {
                "source": key[0],
                "heading": key[1],
                "score": float(getattr(r, "score", 0.0)),
                "source_type": key[2],
            }
        )

    preview_len = 80
    message_summaries: list[dict[str, Any]] = []
    for idx, msg in enumerate(messages):
        content = msg.get("content", "")
        chars = estimate_content_chars(content)
        tokens = (
            per_message_tokens[idx]
            if idx < len(per_message_tokens)
            else rough_tokens_from_chars(chars)
        )
        preview_src = content if isinstance(content, str) else str(content)
        preview = preview_src[:preview_len].replace("\n", " ")
        if len(preview_src) > preview_len:
            preview += "…"
        message_summaries.append(
            {
                "role": msg.get("role", ""),
                "chars": chars,
                "tokens": tokens,
                "preview": preview,
            }
        )

    sys_chars = estimate_content_chars(messages[0].get("content", "")) if messages else 0

    scope_thread_slugs = _compiled_scope_thread_slugs(compiled)
    injected_messages = _compiled_injected_messages(compiled)

    return {
        "channel": channel,
        "chat_id": chat_id,
        "mode": mode,
        "model": model,
        "tools_count": len(tools),
        "messages": messages,
        "message_summaries": message_summaries,
        "history_message_count": len(history),
        "history_chars": sum(estimate_content_chars(h.get("content", "")) for h in history),
        "history_tokens": history_tokens,
        "recall_count": len(recall_items),
        "recall_items": recall_items,
        "scope_thread_slugs": scope_thread_slugs,
        "message_inject_count": len(injected_messages),
        "recalled_thread_slugs": sorted(compiled.recalled_thread_slugs),
        "system_prompt_chars": sys_chars,
        "system_prompt_tokens": system_prompt_tokens,
        "total_input_chars": sum(estimate_content_chars(m.get("content", "")) for m in messages),
        "total_input_tokens": token_estimate.get("messages_only", 0),
        "history_config": {
            "memory_budget_tokens": hc.memory_budget_tokens,
            "recall_max_total_tokens": hc.recall_max_total_tokens,
            "recall_max_per_item_tokens": hc.recall_max_per_item_tokens,
            "session_scoped": session_history is not None,
        },
        "session_id": session_id,
        "token_estimate": token_estimate,
    }


__all__ = [
    "build_context_inspection",
    "_estimate_messages_tokens",
    "_estimate_per_message_tokens",
    "_estimate_prompt_tokens",
]
