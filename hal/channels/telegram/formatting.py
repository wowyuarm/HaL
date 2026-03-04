"""Formatting helpers for Telegram message rendering."""

from __future__ import annotations

import re

from .constants import CTX_OUTPUT_MAX_CHARS


def _markdown_table_to_pre(table_text: str) -> str:
    """Convert markdown table text to a fixed-width Telegram <pre> block."""
    lines = [ln.strip() for ln in table_text.strip().splitlines() if ln.strip()]
    if not lines:
        return ""

    rows = [_split_table_row(line) for line in lines if not _is_table_separator(line)]
    if not rows:
        return ""

    n_cols = max(len(r) for r in rows)
    col_widths = [_column_width(rows=rows, index=i) for i in range(n_cols)]
    formatted = [_format_table_row(row=row, col_widths=col_widths) for row in rows]
    if len(rows) > 1:
        formatted.insert(1, "  ".join("─" * width for width in col_widths))

    escaped = "\n".join(formatted)
    escaped = escaped.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"<pre>{escaped}</pre>"


def _is_table_separator(line: str) -> bool:
    stripped = line.strip("|").strip()
    return bool(re.match(r"^[\s|:\-]+$", stripped))


def _split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip("|").strip().split("|")]


def _column_width(*, rows: list[list[str]], index: int) -> int:
    return max((len(row[index]) if index < len(row) else 0) for row in rows)


def _format_table_row(*, row: list[str], col_widths: list[int]) -> str:
    padded = [(row[i] if i < len(row) else "").ljust(col_widths[i]) for i in range(len(col_widths))]
    return "  ".join(padded)


def _markdown_to_telegram_html(text: str) -> str:
    """Convert markdown to Telegram-safe HTML."""
    if not text:
        return ""

    code_blocks: list[str] = []

    def save_code_block(m: re.Match) -> str:
        code_blocks.append(m.group(1))
        return f"\x00CB{len(code_blocks) - 1}\x00"

    text = re.sub(r"```[\w]*\n?([\s\S]*?)```", save_code_block, text)

    inline_codes: list[str] = []

    def save_inline_code(m: re.Match) -> str:
        inline_codes.append(m.group(1))
        return f"\x00IC{len(inline_codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", save_inline_code, text)

    table_blocks: list[str] = []

    def save_table(m: re.Match) -> str:
        pre = _markdown_table_to_pre(m.group(0))
        table_blocks.append(pre)
        return f"\x00TB{len(table_blocks) - 1}\x00"

    text = re.sub(
        r"(?:^[ \t]*\|.+\|[ \t]*$\n?){2,}",
        save_table,
        text,
        flags=re.MULTILINE,
    )

    blockquote_blocks: list[str] = []

    def save_blockquote(m: re.Match) -> str:
        lines = m.group(0).rstrip("\n").splitlines()
        inner = "\n".join(re.sub(r"^>\s?", "", line) for line in lines)
        inner = inner.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        blockquote_blocks.append(f"<blockquote>{inner}</blockquote>")
        return f"\x00BQ{len(blockquote_blocks) - 1}\x00\n"

    text = re.sub(r"(?:^>.*$\n?)+", save_blockquote, text, flags=re.MULTILINE)

    text = re.sub(r"^[ \t]*[-*_]{3,}[ \t]*$", "━━━━━━━━━━━━━━━━━━━━", text, flags=re.MULTILINE)

    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)

    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)

    text = re.sub(r"(?<![a-zA-Z0-9])_([^_]+)_(?![a-zA-Z0-9])", r"<i>\1</i>", text)
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)

    text = re.sub(r"^(\s*)[-*]\s+", r"\1• ", text, flags=re.MULTILINE)
    text = re.sub(r"(?<![a-zA-Z0-9\*])\*([^*\n]+?)\*(?![a-zA-Z0-9\*])", r"<i>\1</i>", text)

    for i, code in enumerate(inline_codes):
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00IC{i}\x00", f"<code>{escaped}</code>")

    for i, code in enumerate(code_blocks):
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00CB{i}\x00", f"<pre><code>{escaped}</code></pre>")

    for i, tbl in enumerate(table_blocks):
        text = text.replace(f"\x00TB{i}\x00", tbl)

    for i, bq in enumerate(blockquote_blocks):
        text = text.replace(f"\x00BQ{i}\x00", bq)

    return text


def split_telegram_message(text: str, max_length: int = 4000) -> list[str]:
    """Split long text into Telegram-safe chunks."""
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    remaining = text

    while len(remaining) > max_length:
        split_pos = remaining.rfind("\n", 0, max_length + 1)
        if split_pos <= 0:
            split_pos = remaining.rfind(" ", 0, max_length + 1)
        if split_pos <= 0:
            split_pos = max_length

        chunks.append(remaining[:split_pos])
        remaining = remaining[split_pos:]
        remaining = remaining.lstrip("\n ")

    if remaining:
        chunks.append(remaining)

    return chunks


def stringify_message_content(content: object) -> str:
    """Render heterogeneous message content to text."""
    import json

    if isinstance(content, str):
        return content
    if isinstance(content, (list, dict)):
        return json.dumps(content, ensure_ascii=False, indent=2)
    if content is None:
        return ""
    return str(content)


def compress_head_tail(text: str, max_chars: int) -> str:
    """Compress text by keeping head+tail under max_chars."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text

    marker_tpl = "\n\n...[omitted {} chars for readability]...\n\n"
    marker = marker_tpl.format(0)
    budget = max_chars - len(marker)
    if budget <= 40:
        return text[:max_chars]

    head = int(budget * 0.65)
    tail = max(budget - head, 0)
    omitted = max(len(text) - head - tail, 0)
    marker = marker_tpl.format(omitted)

    budget = max(max_chars - len(marker), 0)
    if budget <= 40:
        return text[:max_chars]

    head = int(budget * 0.65)
    tail = max(budget - head, 0)
    omitted = max(len(text) - head - tail, 0)
    marker = marker_tpl.format(omitted)

    head_text = text[:head].rstrip()
    tail_text = text[-tail:].lstrip() if tail > 0 else ""
    if not tail_text:
        return (head_text + marker).strip()[:max_chars]
    return (head_text + marker + tail_text)[:max_chars]


def compress_context_output(text: str, max_chars: int = CTX_OUTPUT_MAX_CHARS) -> str:
    """Cap context report size for chat UX."""
    if len(text) <= max_chars:
        return text
    return compress_head_tail(text, max_chars=max_chars)
