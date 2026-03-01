"""Telegram channel implementation using python-telegram-bot."""

from __future__ import annotations

import asyncio
import hashlib
import html as html_mod
import json
import re
import subprocess
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger
from telegram import BotCommand, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from hal.bus.events import OutboundMessage
from hal.bus.queue import MessageBus
from hal.channels.base import BaseChannel
from hal.infra.config.schema import TelegramConfig

if TYPE_CHECKING:
    from hal.core.memory.manager import MemoryManager


def _markdown_table_to_pre(table_text: str) -> str:
    """Convert a markdown table to a fixed-width <pre> block for Telegram.

    Accepts a raw markdown table string (with | delimiters and optional
    separator row) and returns an HTML-escaped <pre> block with aligned
    columns.
    """
    lines = [l.strip() for l in table_text.strip().splitlines() if l.strip()]
    if not lines:
        return ""

    # Parse rows into cells, skipping separator lines (e.g. |---|---|)
    rows: list[list[str]] = []
    for line in lines:
        stripped = line.strip("|").strip()
        if re.match(r"^[\s|:\-]+$", stripped):
            continue  # separator row
        cells = [c.strip() for c in stripped.split("|")]
        rows.append(cells)

    if not rows:
        return ""

    # Calculate column widths
    n_cols = max(len(r) for r in rows)
    col_widths = [0] * n_cols
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    # Format rows
    formatted: list[str] = []
    for idx, row in enumerate(rows):
        padded = []
        for i in range(n_cols):
            cell = row[i] if i < len(row) else ""
            padded.append(cell.ljust(col_widths[i]))
        formatted.append("  ".join(padded))
        # Add separator after header row
        if idx == 0 and len(rows) > 1:
            formatted.append("  ".join("─" * w for w in col_widths))

    escaped = "\n".join(formatted)
    escaped = escaped.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"<pre>{escaped}</pre>"


def _markdown_to_telegram_html(text: str) -> str:
    """Convert markdown to Telegram-safe HTML.

    Supports: code blocks, inline code, tables, headers, blockquotes,
    bold, italic, strikethrough, links, bullet/ordered lists, and
    horizontal rules.
    """
    if not text:
        return ""

    # 1. Extract and protect code blocks (preserve content from other processing)
    code_blocks: list[str] = []

    def save_code_block(m: re.Match) -> str:
        code_blocks.append(m.group(1))
        return f"\x00CB{len(code_blocks) - 1}\x00"

    text = re.sub(r"```[\w]*\n?([\s\S]*?)```", save_code_block, text)

    # 2. Extract and protect inline code
    inline_codes: list[str] = []

    def save_inline_code(m: re.Match) -> str:
        inline_codes.append(m.group(1))
        return f"\x00IC{len(inline_codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", save_inline_code, text)

    # 3. Extract and protect markdown tables -> <pre> blocks
    table_blocks: list[str] = []

    def save_table(m: re.Match) -> str:
        pre = _markdown_table_to_pre(m.group(0))
        table_blocks.append(pre)
        return f"\x00TB{len(table_blocks) - 1}\x00"

    # Match consecutive lines starting with |
    text = re.sub(
        r"(?:^[ \t]*\|.+\|[ \t]*$\n?){2,}",
        save_table,
        text,
        flags=re.MULTILINE,
    )

    # 4. Horizontal rules --- or *** or ___ -> unicode line (before HTML escape)
    text = re.sub(r"^[ \t]*[-*_]{3,}[ \t]*$", "━━━━━━━━━━━━━━━━━━━━", text, flags=re.MULTILINE)

    # 5. Escape HTML special characters FIRST (before generating any HTML tags)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # 6. Headers # Title -> <b>Title</b> (after escape, so title text is safe)
    text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    # 7. Blockquotes &gt; text -> <blockquote>text</blockquote>
    # After HTML escape, > became &gt; so match that
    def collapse_blockquotes(m: re.Match) -> str:
        lines = m.group(0).splitlines()
        inner = "\n".join(re.sub(r"^&gt;\s?", "", l) for l in lines)
        return f"<blockquote>{inner}</blockquote>\n"

    text = re.sub(r"(?:^&gt;.*$\n?)+", collapse_blockquotes, text, flags=re.MULTILINE)

    # 8. Links [text](url) - must be before bold/italic to handle nested cases
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)

    # 9. Bold **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)

    # 10. Italic _text_ (avoid matching inside words like some_var_name)
    text = re.sub(r"(?<![a-zA-Z0-9])_([^_]+)_(?![a-zA-Z0-9])", r"<i>\1</i>", text)

    # 11. Strikethrough ~~text~~
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)

    # 12. Bullet lists - item or * item -> • item (preserve leading indentation)
    text = re.sub(r"^(\s*)[-*]\s+", r"\1• ", text, flags=re.MULTILINE)

    # 12.5 Single-asterisk italic *text* (after bold and bullet processing)
    text = re.sub(r"(?<![a-zA-Z0-9\*])\*([^*]+)\*(?![a-zA-Z0-9\*])", r"<i>\1</i>", text)

    # 13. Ordered lists  1. item -> 1. item (preserve numbering, just clean indent)
    text = re.sub(r"^(\d+)\.\s+", r"\1. ", text, flags=re.MULTILINE)

    # 14. Restore inline code with HTML tags
    for i, code in enumerate(inline_codes):
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00IC{i}\x00", f"<code>{escaped}</code>")

    # 15. Restore code blocks with HTML tags
    for i, code in enumerate(code_blocks):
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00CB{i}\x00", f"<pre><code>{escaped}</code></pre>")

    # 16. Restore table blocks (already contain valid HTML)
    for i, tbl in enumerate(table_blocks):
        text = text.replace(f"\x00TB{i}\x00", tbl)

    return text


# ---------------------------------------------------------------------------
# /context output constants
# ---------------------------------------------------------------------------
_CTX_SYSTEM_PREVIEW_CHARS = 2400
_CTX_MESSAGE_PREVIEW_CHARS = 900
_CTX_OUTPUT_MAX_CHARS = 12000


class TelegramChannel(BaseChannel):
    """
    Telegram channel using long polling.

    Simple and reliable - no webhook/public IP needed.
    """

    name = "telegram"

    # Commands registered with Telegram's command menu
    BOT_COMMANDS = [
        BotCommand("start", "Start the bot"),
        BotCommand("reset", "Reset conversation history"),
        BotCommand("context", "Show current LLM context"),
        BotCommand("help", "Show available commands"),
    ]

    def __init__(
        self,
        config: TelegramConfig,
        bus: MessageBus,
        groq_api_key: str = "",
        memory_manager: MemoryManager | None = None,
        context_inspector: Callable[[str, str, str], Awaitable[dict[str, Any]]] | None = None,
    ):
        super().__init__(config, bus)
        self.config: TelegramConfig = config
        self.groq_api_key = groq_api_key
        self.memory_manager = memory_manager
        self._context_inspector = context_inspector
        self._app: Application | None = None
        self._chat_ids: dict[str, int] = {}  # Map sender_id to chat_id for replies
        self._typing_tasks: dict[str, asyncio.Task] = {}  # chat_id -> typing loop task

    async def start(self) -> None:
        """Start the Telegram bot with long polling."""
        if not self.config.token:
            logger.error("Telegram bot token not configured")
            return

        self._running = True

        # Build the application
        builder = Application.builder().token(self.config.token)
        if self.config.proxy:
            builder = builder.proxy(self.config.proxy).get_updates_proxy(self.config.proxy)
        self._app = builder.build()

        # Add command handlers
        self._app.add_handler(CommandHandler("start", self._on_start))
        self._app.add_handler(CommandHandler("reset", self._on_reset))
        self._app.add_handler(CommandHandler("context", self._on_context))
        self._app.add_handler(CommandHandler("help", self._on_help))

        # Add message handler for text, photos, voice, documents
        self._app.add_handler(
            MessageHandler(
                (
                    filters.TEXT
                    | filters.PHOTO
                    | filters.VOICE
                    | filters.AUDIO
                    | filters.Document.ALL
                )
                & ~filters.COMMAND,
                self._on_message,
            )
        )

        logger.info("Starting Telegram bot (polling mode)...")

        # Initialize and start polling
        await self._app.initialize()
        await self._app.start()

        # Get bot info and register command menu
        bot_info = await self._app.bot.get_me()
        logger.info(f"Telegram bot @{bot_info.username} connected")

        try:
            await self._app.bot.set_my_commands(self.BOT_COMMANDS)
            logger.debug("Telegram bot commands registered")
        except Exception as e:
            logger.warning(f"Failed to register bot commands: {e}")

        # Start polling (this runs until stopped)
        await self._app.updater.start_polling(
            allowed_updates=["message"],
            drop_pending_updates=True,  # Ignore old messages on startup
        )

        # Send startup notification to the first allowed user
        await self._send_startup_notification()

        # Keep running until stopped
        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop the Telegram bot."""
        self._running = False

        # Cancel all typing indicators
        for chat_id in list(self._typing_tasks):
            self._stop_typing(chat_id)

        if self._app:
            logger.info("Stopping Telegram bot...")
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            self._app = None

    async def _send_startup_notification(self) -> None:
        """Send a startup notification to the first allowed user."""
        allow_list = getattr(self.config, "allow_from", [])
        owner_id = next((uid for uid in allow_list if uid.isdigit()), None)
        if not owner_id or not self._app:
            return

        try:
            result = subprocess.run(
                ["git", "log", "-1", "--format=%h %s"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            commit_info = result.stdout.strip() if result.returncode == 0 else "unknown"
        except Exception:
            commit_info = "unknown"

        text = f"\U0001f534 HaL online — {commit_info}"
        try:
            await self._app.bot.send_message(chat_id=int(owner_id), text=text)
            logger.info(f"Startup notification sent to {owner_id}")
        except Exception as e:
            logger.warning(f"Failed to send startup notification: {e}")

    def _split_telegram_message(self, text: str, max_length: int = 4000) -> list[str]:
        """
        将长文本拆分为多个 Telegram 消息块。

        策略（仿照 PR #694）：
        1. 优先在换行符处拆分
        2. 次选在空格处拆分
        3. 如果没有好的分割点，强制在 max_length 处拆分
        """
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

    async def _reply_long_text(
        self,
        update: Update,
        text: str,
        *,
        parse_mode: str | None = None,
    ) -> None:
        """Reply in multiple chunks when text exceeds Telegram limits."""
        if not update.message:
            return
        for chunk in self._split_telegram_message(text, max_length=4000):
            await update.message.reply_text(chunk, parse_mode=parse_mode)

    @staticmethod
    def _sender_id_for_allowlist(user: Any) -> str:
        """Build sender ID compatible with BaseChannel allowlist checks."""
        sender_id = str(getattr(user, "id", ""))
        username = getattr(user, "username", None)
        if username:
            sender_id = f"{sender_id}|{username}"
        return sender_id

    @staticmethod
    def _stringify_message_content(content: Any) -> str:
        """Render heterogeneous message content to text for debug output."""
        if isinstance(content, str):
            return content
        if isinstance(content, (list, dict)):
            return json.dumps(content, ensure_ascii=False, indent=2)
        if content is None:
            return ""
        return str(content)

    @staticmethod
    def _compress_head_tail(text: str, max_chars: int) -> str:
        """Compress text by keeping head+tail within a hard character budget."""
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

        # Recalculate once with the actual marker length so the hard cap still holds.
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

    @staticmethod
    def _compress_context_output(text: str, max_chars: int = _CTX_OUTPUT_MAX_CHARS) -> str:
        """Keep head+tail when context dump is too long for chat UX."""
        if len(text) <= max_chars:
            return text

        return TelegramChannel._compress_head_tail(text, max_chars=max_chars)

    # ------------------------------------------------------------------
    # /context report — sub-formatters (all return HTML-safe strings)
    # ------------------------------------------------------------------

    @staticmethod
    def _fmt_ctx_header(data: dict[str, Any], *, full_messages: bool) -> str:
        """Session metadata header."""
        e = html_mod.escape
        view = "full" if full_messages else "compact"
        return (
            f"📋 <b>HaL Context Inspector</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Session</b>  {e(data.get('channel', ''))}:{e(data.get('chat_id', ''))}\n"
            f"<b>Model</b>   {e(data.get('model', ''))}\n"
            f"<b>Mode</b>    {e(data.get('mode', 'collab'))} ({view})"
        )

    @staticmethod
    def _fmt_ctx_snapshot(data: dict[str, Any]) -> str:
        """Core size metrics."""
        te = data.get("token_estimate") or {}
        tok_prompt = te.get("messages_only", 0)
        tok_tools = te.get("tools_only", 0)
        return (
            f"📊 <b>Context Size</b>\n"
            f"  system_prompt   {data.get('system_prompt_chars', 0):,} chars\n"
            f"  history         {data.get('history_message_count', 0)} msgs"
            f" / {data.get('history_chars', 0):,} chars\n"
            f"  recall          {data.get('recall_count', 0)} hits\n"
            f"  total           {data.get('total_input_chars', 0):,} chars\n"
            f"  tokens (est.)   {tok_prompt:,} prompt + {tok_tools:,} tools"
        )

    @staticmethod
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

    @staticmethod
    def _fmt_ctx_messages(
        data: dict[str, Any],
        *,
        full_messages: bool,
    ) -> str:
        """Message list — summaries by default, full content in full mode."""
        e = html_mod.escape
        messages = data.get("messages") or []
        summaries = data.get("message_summaries") or []
        lines = [f"💬 <b>Messages</b> ({len(summaries)})"]

        if full_messages:
            for idx, msg in enumerate(messages):
                role = msg.get("role", "?")
                content = TelegramChannel._stringify_message_content(msg.get("content", ""))
                chars = len(content)
                lines.append(f"\n[{idx}] {role}  {chars:,}c")
                if role == "system":
                    digest = hashlib.sha256(content.encode()).hexdigest()[:16]
                    lines.append(f"(sha256={digest})")
                    lines.append(
                        TelegramChannel._compress_head_tail(
                            e(content), max_chars=_CTX_SYSTEM_PREVIEW_CHARS
                        )
                    )
                else:
                    lines.append(
                        TelegramChannel._compress_head_tail(
                            e(content), max_chars=_CTX_MESSAGE_PREVIEW_CHARS
                        )
                    )
        else:
            for idx, s in enumerate(summaries):
                role = s.get("role", "?")
                chars = s.get("chars", 0)
                preview = e(s.get("preview", ""))
                tag = role[:4]
                lines.append(f'  [{idx}] {tag:<4}  {chars:>6,}c  "{preview}"')
        return "\n".join(lines)

    @staticmethod
    def _fmt_ctx_last_run(latest_metrics: dict[str, Any] | None) -> str:
        """Last actual LLM usage metrics."""
        if not isinstance(latest_metrics, dict):
            return "📈 <b>Last Run</b>  none"
        prompt = latest_metrics.get("first_prompt_tokens") or 0
        comp = latest_metrics.get("first_completion_tokens") or 0
        tools_used = latest_metrics.get("tools_used") or []
        parts = [
            "📈 <b>Last Run</b>",
            f"  tokens: {prompt:,} → {comp:,} (prompt → completion)",
        ]
        if tools_used:
            parts.append(f"  tools: {', '.join(tools_used)}")
        return "\n".join(parts)

    def _format_context_report(
        self,
        data: dict[str, Any],
        *,
        full_messages: bool = False,
    ) -> str:
        """Format inspect_context() payload as Telegram HTML."""
        sections = [
            self._fmt_ctx_header(data, full_messages=full_messages),
            self._fmt_ctx_snapshot(data),
            self._fmt_ctx_recall(data.get("recall_items") or []),
            self._fmt_ctx_messages(data, full_messages=full_messages),
            self._fmt_ctx_last_run(data.get("latest_metrics")),
        ]
        return self._compress_context_output("\n\n".join(sections))

    def _get_media_type(self, path: str) -> str:
        """Infer Telegram media type from file extension."""
        path = path.lower()
        if path.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
            return "photo"
        if path.endswith(".ogg"):
            return "voice"
        if path.endswith((".mp3", ".m4a", ".wav", ".aac")):
            return "audio"
        return "document"

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Telegram."""
        if not self._app:
            logger.warning("Telegram bot not running")
            return

        # Stop typing indicator for this chat
        self._stop_typing(msg.chat_id)

        try:
            chat_id = int(msg.chat_id)
        except ValueError:
            logger.error(f"Invalid chat_id: {msg.chat_id}")
            return

        # Send media files first
        if msg.media:
            for media_path in msg.media:
                try:
                    media_type = self._get_media_type(media_path)
                    with open(media_path, "rb") as f:
                        if media_type == "photo":
                            await self._app.bot.send_photo(chat_id=chat_id, photo=f)
                        elif media_type == "voice":
                            await self._app.bot.send_voice(chat_id=chat_id, voice=f)
                        elif media_type == "audio":
                            await self._app.bot.send_audio(chat_id=chat_id, audio=f)
                        else:
                            await self._app.bot.send_document(chat_id=chat_id, document=f)
                except Exception as e:
                    logger.error(f"Failed to send media {media_path}: {e}")
                    await self._app.bot.send_message(
                        chat_id=chat_id, text=f"[Failed to send file: {media_path}]"
                    )

        # Send text content if present
        if msg.content and msg.content != "[empty message]":
            # Split markdown first, then convert each chunk to HTML to avoid breaking tags.
            for chunk in self._split_telegram_message(msg.content):
                try:
                    html_chunk = _markdown_to_telegram_html(chunk)
                    await self._app.bot.send_message(
                        chat_id=chat_id, text=html_chunk, parse_mode="HTML"
                    )
                except Exception as e:
                    logger.warning(
                        f"HTML parse failed for one chunk, falling back to plain text: {e}"
                    )
                    try:
                        await self._app.bot.send_message(chat_id=chat_id, text=chunk)
                    except Exception as e2:
                        logger.error(f"Error sending Telegram message chunk: {e2}")

    async def _on_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        if not update.message or not update.effective_user:
            return

        user = update.effective_user
        await update.message.reply_text(
            f"👋 Hi {user.first_name}! I'm HaL.\n\n"
            "Send me a message and I'll respond!\n"
            "Type /help to see available commands."
        )

    async def _on_reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /reset command — clear conversation history."""
        if not update.message or not update.effective_user:
            return

        sender_id = self._sender_id_for_allowlist(update.effective_user)
        if not self.is_allowed(sender_id):
            await update.message.reply_text("⛔ You are not allowed to use this bot.")
            return

        chat_id = str(update.message.chat_id)
        session_key = f"{self.name}:{chat_id}"

        if self.memory_manager is None:
            logger.warning("/reset called but memory_manager is not available")
            await update.message.reply_text("⚠️ Memory management is not available.")
            return

        # Mark a reset point in the conversation log
        self.memory_manager.clear_conversation_history(
            channel=self.name,
            chat_id=chat_id,
        )

        logger.info(f"Conversation reset for {session_key}")
        await update.message.reply_text("🔄 Conversation history cleared. Let's start fresh!")

    async def _on_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command — show available commands."""
        if not update.message:
            return

        help_text = (
            "🔴 <b>HaL commands</b>\n\n"
            "/start — Start the bot\n"
            "/reset — Reset conversation history\n"
            "/context [message] — Inspect current LLM context (compact)\n"
            "/context full [message] — Inspect with raw messages\n"
            "/help — Show this help message\n\n"
            "Just send me a text message to chat!"
        )
        await update.message.reply_text(help_text, parse_mode="HTML")

    async def _on_context(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /context command — dump current LLM input context."""
        if not update.message or not update.effective_user:
            return

        if not self._context_inspector:
            await update.message.reply_text("⚠️ Context inspector is not configured.")
            return

        sender_id = self._sender_id_for_allowlist(update.effective_user)
        if not self.is_allowed(sender_id):
            await update.message.reply_text("⛔ You are not allowed to use this bot.")
            return

        chat_id = str(update.message.chat_id)
        inspect_message = "[context inspection]"
        full_messages = False
        raw = (update.message.text or "").strip()
        if raw:
            parts = raw.split(maxsplit=1)
            if len(parts) > 1:
                tokens = parts[1].strip().split()
                full_messages = "full" in tokens or "--full" in tokens
                tokens = [t for t in tokens if t not in ("full", "--full")]
                if tokens:
                    inspect_message = " ".join(tokens)

        try:
            payload = await self._context_inspector(
                channel=self.name,
                chat_id=chat_id,
                current_message=inspect_message,
            )
            report = self._format_context_report(
                payload,
                full_messages=full_messages,
            )
            await self._reply_long_text(update, report, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"/context failed: {e}")
            await update.message.reply_text("⚠️ Failed to build context snapshot.")

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming messages (text, photos, voice, documents)."""
        if not update.message or not update.effective_user:
            return

        message = update.message
        user = update.effective_user
        chat_id = message.chat_id

        # Use stable numeric ID, but keep username for allowlist compatibility
        sender_id = str(user.id)
        if user.username:
            sender_id = f"{sender_id}|{user.username}"

        # Store chat_id for replies
        self._chat_ids[sender_id] = chat_id

        # Build content from text and/or media
        content_parts = []
        media_paths = []

        # Text content
        if message.text:
            content_parts.append(message.text)
        if message.caption:
            content_parts.append(message.caption)

        # Handle media files
        media_file = None
        media_type = None

        if message.photo:
            media_file = message.photo[-1]  # Largest photo
            media_type = "image"
        elif message.voice:
            media_file = message.voice
            media_type = "voice"
        elif message.audio:
            media_file = message.audio
            media_type = "audio"
        elif message.document:
            media_file = message.document
            media_type = "file"

        # Download media if present
        if media_file and self._app:
            try:
                file = await self._app.bot.get_file(media_file.file_id)
                ext = self._get_extension(media_type, getattr(media_file, "mime_type", None))

                # Save to media/received/ (user uploads via channel)
                from pathlib import Path

                media_dir = Path.home() / ".hal" / "media" / "received"
                media_dir.mkdir(parents=True, exist_ok=True)

                file_path = media_dir / f"{media_file.file_id[:16]}{ext}"
                await file.download_to_drive(str(file_path))

                media_paths.append(str(file_path))

                # Handle voice transcription
                if media_type == "voice" or media_type == "audio":
                    from hal.infra.providers.transcription import GroqTranscriptionProvider

                    transcriber = GroqTranscriptionProvider(api_key=self.groq_api_key)
                    transcription = await transcriber.transcribe(file_path)
                    if transcription:
                        logger.info(f"Transcribed {media_type}: {transcription[:50]}...")
                        content_parts.append(f"[transcription: {transcription}]")
                    else:
                        content_parts.append(f"[{media_type}: {file_path}]")
                else:
                    content_parts.append(f"[{media_type}: {file_path}]")

                logger.debug(f"Downloaded {media_type} to {file_path}")
            except Exception as e:
                logger.error(f"Failed to download media: {e}")
                content_parts.append(f"[{media_type}: download failed]")

        content = "\n".join(content_parts) if content_parts else "[empty message]"

        logger.debug(f"Telegram message from {sender_id}: {content[:50]}...")

        str_chat_id = str(chat_id)

        # Start typing indicator before processing
        self._start_typing(str_chat_id)

        # Forward to the message bus
        await self._handle_message(
            sender_id=sender_id,
            chat_id=str_chat_id,
            content=content,
            media=media_paths,
            metadata={
                "message_id": message.message_id,
                "user_id": user.id,
                "username": user.username,
                "first_name": user.first_name,
                "is_group": message.chat.type != "private",
            },
        )

    def _start_typing(self, chat_id: str) -> None:
        """Start sending 'typing...' indicator for a chat."""
        # Cancel any existing typing task for this chat
        self._stop_typing(chat_id)
        self._typing_tasks[chat_id] = asyncio.create_task(self._typing_loop(chat_id))

    def _stop_typing(self, chat_id: str) -> None:
        """Stop the typing indicator for a chat."""
        task = self._typing_tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()

    async def _typing_loop(self, chat_id: str) -> None:
        """Repeatedly send 'typing' action until cancelled."""
        try:
            while self._app:
                await self._app.bot.send_chat_action(chat_id=int(chat_id), action="typing")
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"Typing indicator stopped for {chat_id}: {e}")

    def _get_extension(self, media_type: str, mime_type: str | None) -> str:
        """Get file extension based on media type."""
        if mime_type:
            ext_map = {
                "image/jpeg": ".jpg",
                "image/png": ".png",
                "image/gif": ".gif",
                "audio/ogg": ".ogg",
                "audio/mpeg": ".mp3",
                "audio/mp4": ".m4a",
            }
            if mime_type in ext_map:
                return ext_map[mime_type]

        type_map = {"image": ".jpg", "voice": ".ogg", "audio": ".mp3", "file": ""}
        return type_map.get(media_type, "")
