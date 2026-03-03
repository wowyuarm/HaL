"""Telegram slash command handlers."""

from __future__ import annotations

from loguru import logger
from telegram import Update
from telegram.ext import ContextTypes


class TelegramCommandsMixin:
    """Telegram slash command handlers."""

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
        """Handle /reset command and clear conversation history."""
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

        self.memory_manager.clear_conversation_history(channel=self.name, chat_id=chat_id)

        logger.info(f"Conversation reset for {session_key}")
        await update.message.reply_text("🔄 Conversation history cleared. Let's start fresh!")

    async def _on_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command."""
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
        """Handle /context command and dump current LLM input context."""
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
            report = self._format_context_report(payload, full_messages=full_messages)
            await self._reply_long_text(update, report, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"/context failed: {e}")
            await update.message.reply_text("⚠️ Failed to build context snapshot.")
