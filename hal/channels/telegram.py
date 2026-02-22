"""Telegram channel implementation using python-telegram-bot."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
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


def _markdown_to_telegram_html(text: str) -> str:
    """
    Convert markdown to Telegram-safe HTML.
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

    # 3. Headers # Title -> just the title text
    text = re.sub(r"^#{1,6}\s+(.+)$", r"\1", text, flags=re.MULTILINE)

    # 4. Blockquotes > text -> just the text (before HTML escaping)
    text = re.sub(r"^>\s*(.*)$", r"\1", text, flags=re.MULTILINE)

    # 5. Escape HTML special characters
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # 6. Links [text](url) - must be before bold/italic to handle nested cases
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)

    # 7. Bold **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)

    # 8. Italic _text_ (avoid matching inside words like some_var_name)
    text = re.sub(r"(?<![a-zA-Z0-9])_([^_]+)_(?![a-zA-Z0-9])", r"<i>\1</i>", text)

    # 9. Strikethrough ~~text~~
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)

    # 10. Bullet lists - item -> • item
    text = re.sub(r"^[-*]\s+", "• ", text, flags=re.MULTILINE)

    # 11. Restore inline code with HTML tags
    for i, code in enumerate(inline_codes):
        # Escape HTML in code content
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00IC{i}\x00", f"<code>{escaped}</code>")

    # 12. Restore code blocks with HTML tags
    for i, code in enumerate(code_blocks):
        # Escape HTML in code content
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00CB{i}\x00", f"<pre><code>{escaped}</code></pre>")

    return text


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

    async def _reply_long_text(self, update: Update, text: str) -> None:
        """Reply in multiple chunks when text exceeds Telegram limits."""
        if not update.message:
            return
        for chunk in self._split_telegram_message(text, max_length=4000):
            await update.message.reply_text(chunk)

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
    def _compress_context_output(text: str, max_chars: int = 12000) -> str:
        """Keep head+tail when context dump is too long for chat UX."""
        if len(text) <= max_chars:
            return text

        return TelegramChannel._compress_head_tail(text, max_chars=max_chars)

    def _format_context_report(
        self,
        data: dict[str, Any],
        inspect_message: str,
        *,
        full_messages: bool = False,
    ) -> str:
        """Format inspect_context() payload for Telegram output."""
        history_config = data.get("history_config") or {}
        history_window = data.get("history_window") or []
        scanned_days = ", ".join(
            f"{item.get('date', '?')}:{'yes' if item.get('exists') else 'no'}"
            for item in history_window
        )
        lines: list[str] = [
            "HaL Context Inspector",
            f"session: {data.get('channel', self.name)}:{data.get('chat_id', '')}",
            f"model: {data.get('model', '')}",
            f"mode: {data.get('mode', 'collab')}",
            f"view: {'full' if full_messages else 'compact'}",
            "",
            "Input Snapshot",
            f"- inspect_message_chars: {len(inspect_message)}",
            f"- history_messages: {data.get('history_message_count', 0)}",
            f"- history_chars: {data.get('history_chars', 0)}",
            f"- recall_count: {data.get('recall_count', 0)}",
            f"- system_prompt_chars: {data.get('system_prompt_chars', 0)}",
            f"- total_input_chars: {data.get('total_input_chars', 0)}",
        ]

        token_estimate = data.get("token_estimate") or {}
        lines.extend(
            [
                "",
                "Token Estimate",
                f"- method: {token_estimate.get('method', 'unknown')}",
                f"- messages_only: {token_estimate.get('messages_only', 0)}",
                f"- with_tools: {token_estimate.get('with_tools', 0)}",
                f"- tools_only: {token_estimate.get('tools_only', 0)}",
            ]
        )

        lines.extend(
            [
                "",
                "History Build",
                f"- history_days: {history_config.get('history_days', 1)}",
                f"- max_messages: {history_config.get('max_messages', 0)}",
                f"- max_history_chars: {history_config.get('max_history_chars', 0)}",
                f"- recent_full_turns: {history_config.get('recent_full_turns', 0)}",
                f"- assistant_truncate_chars: {history_config.get('assistant_truncate_chars', 0)}",
            ]
        )
        if scanned_days:
            lines.append(f"- scanned_days(date:file_exists): {scanned_days}")

        latest_metrics = data.get("latest_metrics")
        lines.append("")
        lines.append("Latest Actual Usage")
        if isinstance(latest_metrics, dict):
            lines.extend(
                [
                    f"- timestamp: {latest_metrics.get('timestamp', '')}",
                    f"- first_prompt_tokens: {latest_metrics.get('first_prompt_tokens')}",
                    f"- first_completion_tokens: {latest_metrics.get('first_completion_tokens')}",
                    f"- first_total_tokens: {latest_metrics.get('first_total_tokens')}",
                    f"- loop_iterations: {latest_metrics.get('loop_iterations', 0)}",
                    f"- tools_used: {', '.join(latest_metrics.get('tools_used', [])) or 'none'}",
                    f"- spawn_total_tokens: {latest_metrics.get('spawn_total_tokens', 0)}",
                ]
            )
        else:
            lines.append("- none (no previous completed loop for this session)")

        recall_items = data.get("recall_items") or []
        if recall_items:
            unique_recall_items: list[dict[str, Any]] = []
            seen: set[tuple[str, str, str, str]] = set()
            for item in recall_items:
                key = (
                    str(item.get("source", "")),
                    str(item.get("heading", "")),
                    str(item.get("source_type", "raw")),
                    f"{float(item.get('score', 0.0)):.4f}",
                )
                if key in seen:
                    continue
                seen.add(key)
                unique_recall_items.append(item)

            lines.append("")
            lines.append("Recall Hits")
            if len(unique_recall_items) < len(recall_items):
                lines.append(
                    f"- deduplicated: {len(unique_recall_items)} unique from {len(recall_items)} raw hits"
                )
            for item in unique_recall_items:
                source = item.get("source", "")
                heading = item.get("heading", "")
                score = item.get("score", 0.0)
                source_type = item.get("source_type", "raw")
                lines.append(f"- {source} | {heading} | score={score:.2f} | type={source_type}")

        lines.append("")
        lines.append("Messages Sent To LLM")
        for idx, msg in enumerate(data.get("messages", [])):
            role = msg.get("role", "unknown")
            content = self._stringify_message_content(msg.get("content", ""))
            char_count = len(content)
            lines.append("")
            lines.append(f"[{idx}] role={role} chars={char_count}")

            if full_messages:
                lines.append(content)
                continue

            if role == "system":
                digest = hashlib.sha1(content.encode("utf-8")).hexdigest()[:12]
                lines.append(f"(system prompt compressed, sha1={digest})")
                lines.append(self._compress_head_tail(content, max_chars=2400))
            else:
                lines.append(self._compress_head_tail(content, max_chars=900))

        return self._compress_context_output("\n".join(lines))

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
                args = parts[1].strip()
                if args == "full":
                    full_messages = True
                    args = ""
                elif args.startswith("full "):
                    full_messages = True
                    args = args[5:].strip()
                elif args == "--full":
                    full_messages = True
                    args = ""
                elif args.startswith("--full "):
                    full_messages = True
                    args = args[7:].strip()
                if args:
                    inspect_message = args

        try:
            payload = await self._context_inspector(
                channel=self.name,
                chat_id=chat_id,
                current_message=inspect_message,
            )
            report = self._format_context_report(
                payload,
                inspect_message,
                full_messages=full_messages,
            )
            await self._reply_long_text(update, report)
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
