"""Context report helpers and shared sender utilities."""

from __future__ import annotations

from typing import Any

from telegram import Update

from .constants import MSG_SPLIT_MAX_LENGTH
from .context_report import format_context_report
from .formatting import (
    compress_context_output,
    compress_head_tail,
    split_telegram_message,
    stringify_message_content,
)


class TelegramContextMixin:
    """Context-report behavior shared by command handlers and tests."""

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
        for chunk in split_telegram_message(text, max_length=MSG_SPLIT_MAX_LENGTH):
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
        return stringify_message_content(content)

    @staticmethod
    def _compress_head_tail(text: str, max_chars: int) -> str:
        """Compress text by keeping head+tail within a hard character budget."""
        return compress_head_tail(text, max_chars=max_chars)

    @staticmethod
    def _compress_context_output(text: str, max_chars: int = 12000) -> str:
        """Keep head+tail when context dump is too long for chat UX."""
        return compress_context_output(text, max_chars=max_chars)

    def _format_context_report(
        self,
        data: dict[str, Any],
        *,
        full_messages: bool = False,
    ) -> str:
        """Format inspect_context() payload as Telegram HTML."""
        return format_context_report(data, full_messages=full_messages)
