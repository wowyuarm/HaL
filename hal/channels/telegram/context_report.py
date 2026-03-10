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


def _fmt_ctx_budget(data: dict[str, Any]) -> str:
    """Budget-oriented summary for compact inspection."""
    te = data.get("token_estimate") or {}
    tok_input = int(te.get("messages_only", 0) or 0)
    tok_tools = int(te.get("tools_only", 0) or 0)
    system_tokens = data.get("system_prompt_tokens")
    history_tokens = data.get("history_tokens")
    if not isinstance(system_tokens, int):
        system_tokens = (max(int(data.get("system_prompt_chars", 0)), 0) + 3) // 4
    if not isinstance(history_tokens, int):
        history_tokens = (max(int(data.get("history_chars", 0)), 0) + 3) // 4
    recall_estimate = max(tok_input - system_tokens - history_tokens, 0)
    lines = [
        "📊 <b>Budget</b>",
        f"  input_tokens    {tok_input:,}",
        f"  system          {system_tokens:,}",
        f"  history         {history_tokens:,} ({data.get('history_message_count', 0)} msgs)",
        f"  recall_est      {recall_estimate:,} ({data.get('recall_count', 0)} hits)",
        f"  tools_est       {tok_tools:,}",
    ]
    return "\n".join(lines)


def _fmt_ctx_working_set(data: dict[str, Any]) -> str:
    """High-signal working-set summary for compact inspection."""
    baseline_created = bool(data.get("baseline_created", False))
    baseline_mode = "recompiled-now" if baseline_created else "frozen-session"
    baseline_threads = data.get("baseline_thread_slugs") or []
    recalled_threads = data.get("recalled_thread_slugs") or []
    lines = [
        "🧩 <b>Working Set</b>",
        f"  baseline        {baseline_mode}",
        (
            f"  threads         {len(baseline_threads)} baseline"
            f" / {len(recalled_threads)} recalled"
        ),
    ]
    if baseline_threads:
        lines.append(f"  baseline_slugs  {', '.join(str(slug) for slug in baseline_threads[:4])}")
    if len(baseline_threads) > 4:
        lines.append(f"  baseline_more   +{len(baseline_threads) - 4}")
    if recalled_threads:
        lines.append(f"  recalled_slugs  {', '.join(str(slug) for slug in recalled_threads[:4])}")
    if len(recalled_threads) > 4:
        lines.append(f"  recalled_more   +{len(recalled_threads) - 4}")
    return "\n".join(lines)


def _fmt_ctx_risk(data: dict[str, Any]) -> str:
    """High-signal diagnostic hints for compact inspection."""
    risks: list[str] = []
    system_tokens = data.get("system_prompt_tokens")
    history_tokens = data.get("history_tokens")
    total_tokens = data.get("total_input_tokens")
    if not isinstance(system_tokens, int):
        system_tokens = 0
    if not isinstance(history_tokens, int):
        history_tokens = 0
    if not isinstance(total_tokens, int):
        total_tokens = 0

    if bool(data.get("baseline_created", False)):
        risks.append("baseline was recompiled for this inspection")
    else:
        risks.append("using frozen session baseline")
    if total_tokens and system_tokens / max(total_tokens, 1) >= 0.5:
        risks.append("system prompt dominates current token budget")
    if data.get("history_message_count", 0) == 0:
        risks.append("no session history loaded")
    elif history_tokens <= 32:
        risks.append("history contribution is minimal")
    if data.get("recall_count", 0) == 0:
        risks.append("no recall hits")

    lines = ["⚠️ <b>Risk</b>"]
    for item in risks[:4]:
        lines.append(f"  • {item}")
    return "\n".join(lines)


def _fmt_ctx_recall(recall_items: list[dict[str, Any]], *, detailed: bool) -> str:
    """Recall search hits."""
    if not recall_items:
        return "🔍 <b>Recall</b>  none"
    e = html_mod.escape
    lines = [f"🔍 <b>Recall</b> ({len(recall_items)} hits)"]
    items = recall_items if detailed else recall_items[:2]
    for item in items:
        src = e(item.get("source", ""))
        heading = e(item.get("heading", ""))
        score = item.get("score", 0.0)
        stype = item.get("source_type", "raw")
        lines.append(f'  • {src} | "{heading}" | {score:.2f} {stype}')
    if not detailed and len(recall_items) > len(items):
        lines.append(f"  • +{len(recall_items) - len(items)} more")
    return "\n".join(lines)


def _summary_at(summaries: list[Any], idx: int) -> dict[str, Any] | None:
    """Return summary dict at index when present, else None."""
    if idx < len(summaries) and isinstance(summaries[idx], dict):
        return summaries[idx]
    return None


def _resolve_full_mode_tokens(*, content: str, summary: dict[str, Any] | None) -> int:
    """Resolve token count for full-mode message rendering."""
    if summary is not None:
        s_tokens = summary.get("tokens")
        if isinstance(s_tokens, int) and s_tokens > 0:
            return s_tokens
    return (max(len(content), 0) + 3) // 4


def _compact_summary_tokens(summary: Any) -> int:
    """Resolve compact-mode token count from summary metadata."""
    if not isinstance(summary, dict):
        return 0
    tokens = summary.get("tokens")
    if isinstance(tokens, int):
        return tokens
    chars = summary.get("chars", 0)
    return ((max(int(chars), 0) + 3) // 4) if isinstance(chars, int) else 0


def _format_full_message_lines(
    *,
    idx: int,
    role: str,
    content: str,
    tokens: int,
    escape: Any,
) -> list[str]:
    """Format one full-mode message block."""
    lines = [f"\n[{idx}] {role}  {tokens:,}t"]
    escaped_content = escape(content)
    if role == "system":
        digest = hashlib.sha256(content.encode()).hexdigest()[:16]
        lines.append(f"(sha256={digest})")
        lines.append(compress_head_tail(escaped_content, max_chars=CTX_SYSTEM_PREVIEW_CHARS))
    else:
        lines.append(compress_head_tail(escaped_content, max_chars=CTX_MESSAGE_PREVIEW_CHARS))
    return lines


def _format_compact_summary_line(*, idx: int, summary: Any, escape: Any) -> str:
    """Format one compact-mode summary line."""
    if not isinstance(summary, dict):
        return f'  [{idx}] {"?":<9}  {0:>6,}t  ""'
    role = summary.get("role", "?")
    tokens = _compact_summary_tokens(summary)
    preview = escape(summary.get("preview", ""))
    return f'  [{idx}] {role:<9}  {tokens:>6,}t  "{preview}"'


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
            summary = _summary_at(summaries, idx)
            tokens = _resolve_full_mode_tokens(content=content, summary=summary)
            lines.extend(
                _format_full_message_lines(
                    idx=idx,
                    role=role,
                    content=content,
                    tokens=tokens,
                    escape=e,
                )
            )
    else:
        role_counts: dict[str, int] = {}
        largest_idx = -1
        largest_tokens = -1
        largest_role = "?"
        for idx, summary in enumerate(summaries):
            if isinstance(summary, dict):
                role = str(summary.get("role", "?"))
            else:
                role = "?"
            role_counts[role] = role_counts.get(role, 0) + 1
            tokens = _compact_summary_tokens(summary)
            if tokens > largest_tokens:
                largest_tokens = tokens
                largest_idx = idx
                largest_role = role
        distribution = ", ".join(f"{role} {count}" for role, count in role_counts.items())
        if distribution:
            lines.append(f"  roles           {distribution}")
        if largest_idx >= 0:
            lines.append(
                f"  largest         [{largest_idx}] {largest_role} {max(largest_tokens, 0):,}t"
            )
    return "\n".join(lines)


def _fmt_ctx_debug_meta(data: dict[str, Any]) -> str:
    """Additional metadata shown only in full mode."""
    history_config = data.get("history_config") or {}
    lines = [
        "🛠️ <b>Debug Meta</b>",
        f"  session_key     {html_mod.escape(str(data.get('session_key', '')))}",
        f"  history_scope   {'session' if history_config.get('session_scoped') else 'none'}",
        f"  memory_budget   {history_config.get('memory_budget_tokens', 0)}",
        f"  recall_total    {history_config.get('recall_max_total_tokens', 0)}",
        f"  recall_item     {history_config.get('recall_max_per_item_tokens', 0)}",
    ]
    return "\n".join(lines)


def format_context_report(data: dict[str, Any], *, full_messages: bool = False) -> str:
    """Format inspect_context payload as Telegram HTML."""
    if full_messages:
        sections = [
            _fmt_ctx_header(data, full_messages=full_messages),
            _fmt_ctx_snapshot(data),
            _fmt_ctx_working_set(data),
            _fmt_ctx_recall(data.get("recall_items") or [], detailed=True),
            _fmt_ctx_messages(data, full_messages=full_messages),
            _fmt_ctx_debug_meta(data),
        ]
    else:
        sections = [
            _fmt_ctx_header(data, full_messages=full_messages),
            _fmt_ctx_budget(data),
            _fmt_ctx_working_set(data),
            _fmt_ctx_risk(data),
            _fmt_ctx_recall(data.get("recall_items") or [], detailed=False),
            _fmt_ctx_messages(data, full_messages=full_messages),
        ]
    return compress_context_output("\n\n".join(sections))
