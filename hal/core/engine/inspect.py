"""Context inspection builders for AgentEngine debug output."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

from hal.core.context.token_budget import rough_tokens_from_chars


def _content_char_len(content: Any) -> int:
    """Estimate character length for heterogeneous message content payloads."""
    if content is None:
        return 0
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(_content_char_len(item) for item in content)
    if isinstance(content, dict):
        if "text" in content and isinstance(content["text"], str):
            return len(content["text"])
        return sum(_content_char_len(v) for v in content.values())
    return len(str(content))


def _estimate_messages_tokens(model: str, messages: list[dict[str, Any]]) -> int:
    """Estimate token count for a list of messages."""
    if not messages:
        return 0

    fallback = rough_tokens_from_chars(
        sum(_content_char_len(m.get("content", "")) for m in messages)
    )
    try:
        import litellm

        return int(litellm.token_counter(model=model, messages=messages))
    except Exception:
        return fallback


def _estimate_per_message_tokens(model: str, messages: list[dict[str, Any]]) -> list[int]:
    """Estimate token count for each message (for context inspector display)."""
    fallback = [rough_tokens_from_chars(_content_char_len(m.get("content", ""))) for m in messages]
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
    msg_chars = sum(_content_char_len(m.get("content", "")) for m in messages)
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


def _inspect_history_window(history_days: int, log_dir: Path) -> list[dict[str, Any]]:
    """Build a lightweight debug view of daily log files scanned for history."""
    days = max(history_days, 1)
    today = date.today()
    window: list[dict[str, Any]] = []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        day_str = day.isoformat()
        path = log_dir / f"{day_str}.jsonl"
        window.append({"date": day_str, "exists": path.exists()})
    return window


async def build_context_inspection(
    *,
    provider: Any,
    model: str,
    memory: Any,
    context_builder: Any,
    tools_registry: Any,
    memory_search: Any,
    auto_inject_top_k: int,
    recall_min_score: float,
    history_config: Any,
    channel: str,
    chat_id: str,
    current_message: str,
    mode: str,
) -> dict[str, Any]:
    """Build inspect_context payload without mutating memory state."""
    hc = history_config
    resolved_model = provider.resolve_model(model)
    history = memory.get_conversation_history(
        channel=channel,
        chat_id=chat_id,
        max_messages=hc.max_messages,
        include_tools=False,
        recent_full_turns=hc.recent_full_turns,
        assistant_truncate_tokens=hc.assistant_truncate_tokens,
        max_tokens=hc.max_history_tokens,
        history_days=hc.history_days,
        token_model=resolved_model,
    )

    search_results = []
    if memory_search and current_message.strip():
        try:
            search_results = await memory_search.search(
                current_message,
                top_k=auto_inject_top_k,
                min_score=recall_min_score,
            )
        except Exception as e:
            logger.warning(f"Memory search prefetch failed during inspect: {e}")

    messages = context_builder.build_messages(
        history=history,
        current_message=current_message,
        channel=channel,
        chat_id=chat_id,
        memory_search_results=search_results or None,
        memory_budget_tokens=(hc.memory_budget_tokens or None),
        recall_max_total_tokens=hc.recall_max_total_tokens,
        recall_max_per_item_tokens=hc.recall_max_per_item_tokens,
        token_model=resolved_model,
    )

    tools = tools_registry.get_definitions()
    token_estimate = _estimate_prompt_tokens(resolved_model, messages, tools)
    history_tokens = _estimate_messages_tokens(resolved_model, history)
    system_prompt_tokens = _estimate_messages_tokens(resolved_model, messages[:1])
    per_message_tokens = _estimate_per_message_tokens(resolved_model, messages)
    history_window = _inspect_history_window(hc.history_days, memory.daily_log.data_dir)

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
        chars = _content_char_len(content)
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

    sys_chars = _content_char_len(messages[0].get("content", "")) if messages else 0

    return {
        "channel": channel,
        "chat_id": chat_id,
        "mode": mode,
        "model": model,
        "messages": messages,
        "message_summaries": message_summaries,
        "history_message_count": len(history),
        "history_chars": sum(_content_char_len(h.get("content", "")) for h in history),
        "history_tokens": history_tokens,
        "recall_count": len(recall_items),
        "recall_items": recall_items,
        "system_prompt_chars": sys_chars,
        "system_prompt_tokens": system_prompt_tokens,
        "total_input_chars": sum(_content_char_len(m.get("content", "")) for m in messages),
        "total_input_tokens": token_estimate.get("messages_only", 0),
        "history_config": {
            "history_days": hc.history_days,
            "max_messages": hc.max_messages,
            "max_history_tokens": hc.max_history_tokens,
        },
        "history_window": history_window,
        "token_estimate": token_estimate,
    }


__all__ = [
    "build_context_inspection",
    "_content_char_len",
    "_estimate_messages_tokens",
    "_estimate_per_message_tokens",
    "_estimate_prompt_tokens",
]
