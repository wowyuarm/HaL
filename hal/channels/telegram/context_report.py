"""Context report formatting for Telegram /context output."""

from __future__ import annotations

import hashlib
import html as html_mod
from typing import Any

from .constants import CTX_MESSAGE_PREVIEW_CHARS, CTX_SYSTEM_PREVIEW_CHARS
from .formatting import compress_context_output, compress_head_tail, stringify_message_content


def _fmt_ctx_header(data: dict[str, Any], *, full_messages: bool) -> str:
    """Session metadata header."""
    e = html_mod.escape
    view = "full" if full_messages else "compact"
    return (
        f"📋 <b>HaL Context Inspector</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Session</b>  {e(data.get('channel', ''))}:{e(data.get('chat_id', ''))}\n"
        f"<b>Model</b>   {e(data.get('model', ''))}\n"
        f"<b>Mode</b>    {e(data.get('mode', 'default'))} ({view})"
    )


def _fmt_ctx_snapshot(data: dict[str, Any]) -> str:
    """Core size metrics."""
    e = html_mod.escape
    te = data.get("token_estimate") or {}
    tok_input = te.get("messages_only", 0)
    tok_tools = te.get("tools_only", 0)
    tok_total = te.get("with_tools", tok_input + tok_tools)
    method = te.get("method", "unknown")
    token_error = te.get("error")
    system_tokens = data.get("system_prompt_tokens")
    if not isinstance(system_tokens, int):
        system_tokens = (max(int(data.get("system_prompt_chars", 0)), 0) + 3) // 4
    history_tokens = data.get("history_tokens")
    if not isinstance(history_tokens, int):
        history_tokens = (max(int(data.get("history_chars", 0)), 0) + 3) // 4
    total_tokens = data.get("total_input_tokens")
    if not isinstance(total_tokens, int):
        total_tokens = tok_input

    lines = [
        f"📊 <b>Context Size</b>\n"
        f"  system_prompt   {system_tokens:,} tokens\n"
        f"  history         {data.get('history_message_count', 0)} msgs"
        f" / {history_tokens:,} tokens\n"
        f"  recall          {data.get('recall_count', 0)} hits\n"
        f"  total           {total_tokens:,} tokens\n"
        f"  tokens (est.)   {tok_total:,} total = {tok_input:,} input + {tok_tools:,} tools [{method}]"
    ]
    if token_error:
        lines.append(f"  token_error     {e(str(token_error))[:160]}")
    return "\n".join(lines)


def _fmt_ctx_recall(recall_items: list[dict[str, Any]]) -> str:
    """Recall search hits."""
    if not recall_items:
        return "🔍 <b>Recall</b>  none"
    e = html_mod.escape
    lines = [f"🔍 <b>Recall</b> ({len(recall_items)} hits)"]
    for item in recall_items:
        src = e(item.get("source", ""))
        heading = e(item.get("heading", ""))
        score = item.get("score", 0.0)
        stype = item.get("source_type", "raw")
        lines.append(f'  • {src} | "{heading}" | {score:.2f} {stype}')
    return "\n".join(lines)


def _fmt_ctx_messages(data: dict[str, Any], *, full_messages: bool) -> str:
    """Message list, summaries by default and full content in full mode."""
    e = html_mod.escape
    messages = data.get("messages") or []
    summaries = data.get("message_summaries") or []
    lines = [f"💬 <b>Messages</b> ({len(summaries)})"]

    if full_messages:
        for idx, msg in enumerate(messages):
            role = msg.get("role", "?")
            content = stringify_message_content(msg.get("content", ""))
            tokens = 0
            if idx < len(summaries) and isinstance(summaries[idx], dict):
                s_tokens = summaries[idx].get("tokens")
                if isinstance(s_tokens, int):
                    tokens = s_tokens
            if tokens <= 0:
                tokens = (max(len(content), 0) + 3) // 4
            lines.append(f"\n[{idx}] {role}  {tokens:,}t")
            if role == "system":
                digest = hashlib.sha256(content.encode()).hexdigest()[:16]
                lines.append(f"(sha256={digest})")
                lines.append(compress_head_tail(e(content), max_chars=CTX_SYSTEM_PREVIEW_CHARS))
            else:
                lines.append(compress_head_tail(e(content), max_chars=CTX_MESSAGE_PREVIEW_CHARS))
    else:
        for idx, s in enumerate(summaries):
            role = s.get("role", "?")
            tokens = s.get("tokens")
            if not isinstance(tokens, int):
                chars = s.get("chars", 0)
                tokens = ((max(int(chars), 0) + 3) // 4) if isinstance(chars, int) else 0
            preview = e(s.get("preview", ""))
            lines.append(f'  [{idx}] {role:<9}  {tokens:>6,}t  "{preview}"')
    return "\n".join(lines)


def format_context_report(data: dict[str, Any], *, full_messages: bool = False) -> str:
    """Format inspect_context payload as Telegram HTML."""
    sections = [
        _fmt_ctx_header(data, full_messages=full_messages),
        _fmt_ctx_snapshot(data),
        _fmt_ctx_recall(data.get("recall_items") or []),
        _fmt_ctx_messages(data, full_messages=full_messages),
    ]
    return compress_context_output("\n\n".join(sections))
