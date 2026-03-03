"""Telegram inbound/outbound message handling."""

from __future__ import annotations

import asyncio
from pathlib import Path

from loguru import logger
from telegram import Update
from telegram.ext import ContextTypes

from hal.bus.events import OutboundMessage

from .constants import (
    MSG_SPLIT_MAX_LENGTH,
    PROGRESS_APPEND_DEFAULT_SEPARATOR,
    PROGRESS_APPEND_MODE_CONCAT,
    TYPING_INDICATOR_INTERVAL_S,
)
from .formatting import _markdown_to_telegram_html, split_telegram_message

_APPEND_MODE_META_KEY = "append_mode"
_APPEND_KEY_META_KEY = "append_key"
_APPEND_RESET_META_KEY = "append_reset"
_APPEND_SEPARATOR_META_KEY = "append_separator"
_EMPTY_MESSAGE_SENTINEL = "[empty message]"


class TelegramMessagingMixin:
    """Outbound delivery, media intake, and typing indicator behavior."""

    def _split_telegram_message(self, text: str, max_length: int = 4000) -> list[str]:
        """Split long text into Telegram-sized chunks."""
        return split_telegram_message(text, max_length=max_length)

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

    async def _send_text_chunk(self, chat_id: int, chunk: str) -> int | None:
        """Send one text chunk and return Telegram message_id when available."""
        if not self._app:
            return None
        try:
            html_chunk = _markdown_to_telegram_html(chunk)
            sent = await self._app.bot.send_message(chat_id=chat_id, text=html_chunk, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"HTML parse failed for one chunk, falling back to plain text: {e}")
            try:
                sent = await self._app.bot.send_message(chat_id=chat_id, text=chunk)
            except Exception as e2:
                logger.error(f"Error sending Telegram message chunk: {e2}")
                return None
        return getattr(sent, "message_id", None)

    async def _edit_text_chunk(self, chat_id: int, message_id: int, chunk: str) -> bool:
        """Edit one existing Telegram message chunk."""
        if not self._app:
            return False
        try:
            html_chunk = _markdown_to_telegram_html(chunk)
            await self._app.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=html_chunk,
                parse_mode="HTML",
            )
            return True
        except Exception as e:
            logger.warning(f"HTML edit failed for one chunk, falling back to plain text: {e}")
            try:
                await self._app.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=chunk,
                )
                return True
            except Exception as e2:
                logger.error(f"Error editing Telegram message chunk: {e2}")
                return False

    async def _send_chunked_text(self, chat_id: int, text: str) -> None:
        """Send text as one or more Telegram-sized chunks."""
        for chunk in self._split_telegram_message(text, max_length=MSG_SPLIT_MAX_LENGTH):
            await self._send_text_chunk(chat_id, chunk)

    async def _send_appendable_text(self, chat_id: int, msg: OutboundMessage) -> None:
        """Append text into a stable message thread by editing prior chunks."""
        append_key = str(msg.metadata.get(_APPEND_KEY_META_KEY, ""))
        if not append_key:
            await self._send_chunked_text(chat_id, msg.content)
            return

        state_key = (chat_id, append_key)
        if bool(msg.metadata.get(_APPEND_RESET_META_KEY, False)):
            self._append_buffers.pop(state_key, None)
            self._append_message_ids.pop(state_key, None)

        previous = self._append_buffers.get(state_key, "")
        separator = str(
            msg.metadata.get(_APPEND_SEPARATOR_META_KEY, PROGRESS_APPEND_DEFAULT_SEPARATOR)
        )
        if previous and msg.content:
            combined = f"{previous}{separator}{msg.content}"
        else:
            combined = previous + msg.content

        self._append_buffers[state_key] = combined
        chunks = self._split_telegram_message(combined, max_length=MSG_SPLIT_MAX_LENGTH)
        message_ids = list(self._append_message_ids.get(state_key, []))

        for idx, chunk in enumerate(chunks):
            if idx < len(message_ids):
                message_id = message_ids[idx]
                edited = await self._edit_text_chunk(chat_id, message_id, chunk)
                if edited:
                    continue
                sent_id = await self._send_text_chunk(chat_id, chunk)
                if sent_id is None:
                    self._append_message_ids.pop(state_key, None)
                    return
                message_ids[idx] = sent_id
            else:
                sent_id = await self._send_text_chunk(chat_id, chunk)
                if sent_id is None:
                    self._append_message_ids.pop(state_key, None)
                    return
                message_ids.append(sent_id)

        self._append_message_ids[state_key] = message_ids

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Telegram."""
        if not self._app:
            logger.warning("Telegram bot not running")
            return

        self._stop_typing(msg.chat_id)

        try:
            chat_id = int(msg.chat_id)
        except ValueError:
            logger.error(f"Invalid chat_id: {msg.chat_id}")
            return

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

        if msg.content and msg.content != _EMPTY_MESSAGE_SENTINEL:
            append_mode = msg.metadata.get(_APPEND_MODE_META_KEY)
            if append_mode == PROGRESS_APPEND_MODE_CONCAT:
                await self._send_appendable_text(chat_id, msg)
            else:
                await self._send_chunked_text(chat_id, msg.content)

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming messages (text, photos, voice, documents)."""
        if not update.message or not update.effective_user:
            return

        message = update.message
        user = update.effective_user
        chat_id = message.chat_id

        sender_id = str(user.id)
        if user.username:
            sender_id = f"{sender_id}|{user.username}"

        self._chat_ids[sender_id] = chat_id

        content_parts: list[str] = []
        media_paths: list[str] = []

        if message.text:
            content_parts.append(message.text)
        if message.caption:
            content_parts.append(message.caption)

        media_file = None
        media_type = None

        if message.photo:
            media_file = message.photo[-1]
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

        if media_file and self._app:
            try:
                file = await self._app.bot.get_file(media_file.file_id)
                ext = self._get_extension(media_type, getattr(media_file, "mime_type", None))

                media_dir = Path.home() / ".hal" / "media" / "received"
                media_dir.mkdir(parents=True, exist_ok=True)

                file_path = media_dir / f"{media_file.file_id[:16]}{ext}"
                await file.download_to_drive(str(file_path))

                media_paths.append(str(file_path))

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

        self._start_typing(str_chat_id)

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
        """Start sending typing indicator for a chat."""
        self._stop_typing(chat_id)
        self._typing_tasks[chat_id] = asyncio.create_task(self._typing_loop(chat_id))

    def _stop_typing(self, chat_id: str) -> None:
        """Stop typing indicator for a chat."""
        task = self._typing_tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()

    async def _typing_loop(self, chat_id: str) -> None:
        """Repeatedly send typing action until cancelled."""
        try:
            while self._app:
                await self._app.bot.send_chat_action(chat_id=int(chat_id), action="typing")
                await asyncio.sleep(TYPING_INDICATOR_INTERVAL_S)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"Typing indicator stopped for {chat_id}: {e}")
