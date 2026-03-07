"""Telegram lifecycle and startup notification behavior."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

from loguru import logger
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from hal.bus.events import SystemStartupEvent

from .constants import BOT_COMMANDS, BOT_KEEPALIVE_SLEEP_S, GIT_LOG_TIMEOUT_S


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
        self._app.add_handler(CommandHandler("reset", self._on_reset))
        self._app.add_handler(CommandHandler("context", self._on_context))
        self._app.add_handler(CommandHandler("help", self._on_help))

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

    async def _send_startup_notification(self) -> None:
        """Send startup notification and emit startup event."""
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

        if self.memory_manager:
            if update_info:
                changes = update_info.get("changes", "")
                injection = (
                    f"[System: HaL restarted after self-update. "
                    f"Now running {commit_info}. Changes: {changes}]"
                )
            else:
                injection = f"[System: HaL service started. Now running {commit_info}.]"
            self.memory_manager.record_event(
                session_id=f"startup_{commit_info.split()[0] if commit_info else 'unknown'}",
                event_type="system_startup",
                channel="telegram",
                chat_id=owner_id,
                payload={"content": injection},
            )
            logger.info("Startup context written to event log")

        await self.bus.emit(
            SystemStartupEvent(
                channel="telegram",
                chat_id=owner_id,
                commit_info=commit_info,
                update_info=update_info if update_info else None,
            )
        )

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
