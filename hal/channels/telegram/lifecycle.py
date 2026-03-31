"""Telegram lifecycle and startup notification behavior."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

from loguru import logger
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from .constants import (
    BOT_BOOTSTRAP_RETRIES,
    BOT_COMMANDS,
    BOT_KEEPALIVE_SLEEP_S,
    GIT_LOG_TIMEOUT_S,
)


class TelegramLifecycleMixin:
    """Start/stop and startup notification workflow."""

    BOT_COMMANDS = BOT_COMMANDS

    async def start(self) -> None:
        """Start the Telegram bot with long polling."""
        if not self.config.token:
            logger.error("Telegram bot token not configured")
            return

        self._running = True

        builder = Application.builder().token(self.config.token)
        if self.config.proxy:
            builder = builder.proxy(self.config.proxy).get_updates_proxy(self.config.proxy)
        self._app = builder.build()

        self._app.add_handler(CommandHandler("start", self._on_start))
        self._app.add_handler(CommandHandler("drop", self._on_drop))
        self._app.add_handler(CommandHandler("compact", self._on_compact))
        self._app.add_handler(CommandHandler("context", self._on_context))
        self._app.add_handler(CommandHandler("help", self._on_help))
        self._app.add_handler(CommandHandler("brief", self._on_brief))

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

        await self._app.initialize()
        await self._app.start()

        bot_info = await self._app.bot.get_me()
        logger.info(f"Telegram bot @{bot_info.username} connected")

        try:
            await self._app.bot.set_my_commands(self.BOT_COMMANDS)
            logger.debug("Telegram bot commands registered")
        except Exception as e:
            logger.warning(f"Failed to register bot commands: {e}")

        await self._app.updater.start_polling(
            allowed_updates=["message"],
            drop_pending_updates=True,
            bootstrap_retries=BOT_BOOTSTRAP_RETRIES,
            error_callback=self._on_polling_error,
        )

        await self._send_startup_notification()

        while self._running:
            await asyncio.sleep(BOT_KEEPALIVE_SLEEP_S)

    async def stop(self) -> None:
        """Stop the Telegram bot."""
        self._running = False
        self._append_buffers.clear()
        self._append_message_ids.clear()

        for chat_id in list(self._typing_tasks):
            self._stop_typing(chat_id)

        if self._app:
            logger.info("Stopping Telegram bot...")
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            self._app = None

    async def _on_brief(self, update, context) -> None:
        """Handle /brief command — forward to engine as a normal message."""
        if not update.message or not update.effective_user:
            return

        message = update.message
        user = update.effective_user
        chat_id = message.chat_id

        sender_id = str(user.id)
        if user.username:
            sender_id = f"{sender_id}|{user.username}"

        # Reconstruct full command text (includes /brief + any arguments)
        content = message.text or "/brief"

        str_chat_id = str(chat_id)
        self._start_typing(str_chat_id)
        await self._handle_message(
            sender_id=sender_id,
            chat_id=str_chat_id,
            content=content,
        )

    async def _on_drop(self, update, context) -> None:
        """Handle /drop command — forward to engine to end session without briefing."""
        if not update.message or not update.effective_user:
            return

        message = update.message
        user = update.effective_user
        sender_id = self._sender_id_for_allowlist(user)
        if not self.is_allowed(sender_id):
            await message.reply_text("⛔ You are not allowed to use this bot.")
            return

        str_chat_id = str(message.chat_id)
        sender_id = str(user.id)
        if user.username:
            sender_id = f"{sender_id}|{user.username}"

        await self._handle_message(
            sender_id=sender_id,
            chat_id=str_chat_id,
            content="/drop",
        )

    async def _on_compact(self, update, context) -> None:
        """Handle /compact command — forward to engine for manual session compaction."""
        if not update.message or not update.effective_user:
            return

        message = update.message
        user = update.effective_user
        sender_id = self._sender_id_for_allowlist(user)
        if not self.is_allowed(sender_id):
            await message.reply_text("⛔ You are not allowed to use this bot.")
            return

        str_chat_id = str(message.chat_id)
        sender_id = str(user.id)
        if user.username:
            sender_id = f"{sender_id}|{user.username}"

        content = message.text or "/compact"
        await self._handle_message(
            sender_id=sender_id,
            chat_id=str_chat_id,
            content=content,
        )

    async def _send_startup_notification(self) -> None:
        """Send startup notification to the configured owner, if available."""
        owner_id = self._resolve_owner_id()
        if not owner_id or not self._app:
            return

        try:
            result = subprocess.run(
                ["git", "log", "-1", "--format=%h %s"],
                capture_output=True,
                text=True,
                timeout=GIT_LOG_TIMEOUT_S,
            )
            commit_info = result.stdout.strip() if result.returncode == 0 else "unknown"
        except Exception:
            commit_info = "unknown"

        update_info = self._read_update_marker()

        if update_info:
            changes = update_info.get("changes", "")
            before = update_info.get("before", "?")[:7]
            text = f"\U0001f534 HaL online — {commit_info}\n\nChanges since {before}:\n{changes}"
        else:
            text = f"\U0001f534 HaL online — {commit_info}"

        try:
            await self._app.bot.send_message(chat_id=int(owner_id), text=text)
            logger.info(f"Startup notification sent to {owner_id}")
        except Exception as e:
            logger.warning(f"Failed to send startup notification: {e}")

    def _resolve_owner_id(self) -> str | None:
        """Extract numeric Telegram user ID from allowlist."""
        allow_list = getattr(self.config, "allow_from", [])
        for entry in allow_list:
            if entry.isdigit():
                return entry
            if "|" in entry:
                numeric_part = entry.split("|", 1)[0]
                if numeric_part.isdigit():
                    return numeric_part
        if allow_list:
            logger.warning(
                "allow_from contains no numeric IDs — cannot send startup notification. "
                "Add a numeric Telegram user ID to allow_from."
            )
        return None

    @staticmethod
    def _read_update_marker() -> dict[str, str] | None:
        """Read and consume ~/.hal/last_update.json if present."""
        marker = Path.home() / ".hal" / "last_update.json"
        if not marker.exists():
            return None
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
            marker.unlink()
            logger.info(f"Consumed update marker: {data.get('after', '?')[:7]}")
            return data
        except Exception as e:
            logger.warning(f"Failed to read update marker: {e}")
            return None

    @staticmethod
    def _on_polling_error(error: TelegramError) -> None:
        """Log polling errors without aborting the retry loop."""
        logger.warning(f"Telegram polling error: {error}")
