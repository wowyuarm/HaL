"""TelegramChannel class composed from focused mixins."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from telegram.ext import Application

from hal.bus.queue import MessageBus
from hal.channels.base import BaseChannel
from hal.infra.config.schema import TelegramConfig

from .commands import TelegramCommandsMixin
from .context import TelegramContextMixin
from .lifecycle import TelegramLifecycleMixin
from .messaging import TelegramMessagingMixin


class TelegramChannel(
    TelegramCommandsMixin,
    TelegramContextMixin,
    TelegramMessagingMixin,
    TelegramLifecycleMixin,
    BaseChannel,
):
    """Telegram channel using long polling."""

    name = "telegram"

    def __init__(
        self,
        config: TelegramConfig,
        bus: MessageBus,
        groq_api_key: str = "",
        context_inspector: Callable[[str, str, str], Awaitable[dict[str, Any]]] | None = None,
    ):
        super().__init__(config, bus)
        self.config: TelegramConfig = config
        self.groq_api_key = groq_api_key
        self._context_inspector = context_inspector
        self._app: Application | None = None
        self._chat_ids: dict[str, int] = {}
        self._typing_tasks: dict[str, asyncio.Task] = {}
        self._append_buffers: dict[tuple[int, str], str] = {}
        self._append_message_ids: dict[tuple[int, str], list[int]] = {}
