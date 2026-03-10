"""Context inspection builders for AgentEngine debug output."""

from __future__ import annotations

import json
from typing import Any

from hal.context.compiler import ContextCompiler, SessionTurnRequest
from hal.context.token_budget import rough_tokens_from_chars
from hal.domain.message_payloads import estimate_content_chars


def _estimate_messages_tokens(model: str, messages: list[dict[str, Any]]) -> int:
    """Estimate token count for a list of messages."""
    if not messages:
        return 0

    fallback = rough_tokens_from_chars(
        sum(estimate_content_chars(m.get("content", "")) for m in messages)
    )
    try:
        import litellm

        return int(litellm.token_counter(model=model, messages=messages))
    except Exception:
        return fallback


def _estimate_per_message_tokens(model: str, messages: list[dict[str, Any]]) -> list[int]:
    """Estimate token count for each message (for context inspector display)."""
    fallback = [
        rough_tokens_from_chars(estimate_content_chars(m.get("content", ""))) for m in messages
    ]
    if not messages:
        return fallback

    try:
        import litellm

        return [int(litellm.token_counter(model=model, messages=[m])) for m in messages]
    except Exception:
        return fallback


def _estimate_prompt_tokens(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> dict[str, Any]:
    """Estimate input token usage for context inspection output."""
    msg_chars = sum(estimate_content_chars(m.get("content", "")) for m in messages)
    tools_chars = len(json.dumps(tools, ensure_ascii=False))
    fallback = {
        "method": "chars_div_4",
        "messages_only": rough_tokens_from_chars(msg_chars),
        "with_tools": rough_tokens_from_chars(msg_chars + tools_chars),
        "tools_only": rough_tokens_from_chars(tools_chars),
        "error": None,
    }

    try:
        import litellm

        messages_only = int(litellm.token_counter(model=model, messages=messages))
        with_tools = int(litellm.token_counter(model=model, messages=messages, tools=tools))
        return {
            "method": "litellm.token_counter",
            "messages_only": messages_only,
            "with_tools": with_tools,
            "tools_only": max(with_tools - messages_only, 0),
            "error": None,
        }
    except Exception as e:
        fallback["error"] = str(e)
        return fallback


async def build_context_inspection(
    *,
    provider: Any,
    model: str,
    memory: Any,
    context_builder: Any,
    context_registry: Any,
    tools_registry: Any,
    memory_search: Any,
    auto_inject_top_k: int,
    recall_min_score: float,
    history_config: Any,
    channel: str,
    chat_id: str,
    session_key: str | None = None,
    session_history: list[dict[str, object]] | None = None,
    existing_baseline: str | None = None,
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
        memory_search=memory_search,
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
            existing_baseline=existing_baseline,
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

    return {
        "channel": channel,
        "chat_id": chat_id,
        "mode": mode,
        "model": model,
        "messages": messages,
        "message_summaries": message_summaries,
        "history_message_count": len(history),
        "history_chars": sum(estimate_content_chars(h.get("content", "")) for h in history),
        "history_tokens": history_tokens,
        "recall_count": len(recall_items),
        "recall_items": recall_items,
        "baseline_created": compiled.baseline_created,
        "baseline_thread_slugs": sorted(compiled.baseline_thread_slugs),
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
        "session_key": session_key,
        "token_estimate": token_estimate,
    }


__all__ = [
    "build_context_inspection",
    "_estimate_messages_tokens",
    "_estimate_per_message_tokens",
    "_estimate_prompt_tokens",
]
