from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from hal.bus.queue import MessageBus
from hal.channels.whatsapp import WhatsAppChannel
from hal.infra.config.schema import WhatsAppConfig


@pytest.mark.asyncio
async def test_handle_bridge_message_ignores_invalid_json() -> None:
    ch = WhatsAppChannel(WhatsAppConfig(enabled=True), MessageBus())
    ch._handle_message = AsyncMock()  # type: ignore[method-assign]

    await ch._handle_bridge_message("not-json")
    ch._handle_message.assert_not_called()


@pytest.mark.asyncio
async def test_handle_bridge_message_message_uses_pn_when_present() -> None:
    ch = WhatsAppChannel(WhatsAppConfig(enabled=True), MessageBus())
    ch._handle_message = AsyncMock()  # type: ignore[method-assign]

    payload = {
        "type": "message",
        "pn": "+123456@s.whatsapp.net",
        "sender": "lid_abc@lid.whatsapp.net",
        "content": "hello",
        "id": "m1",
        "timestamp": 123,
        "isGroup": False,
    }

    await ch._handle_bridge_message(json.dumps(payload))

    ch._handle_message.assert_awaited_once()
    kwargs = ch._handle_message.await_args.kwargs
    assert kwargs["sender_id"] == "+123456"
    assert kwargs["chat_id"] == "lid_abc@lid.whatsapp.net"
    assert kwargs["content"] == "hello"
    assert kwargs["metadata"]["message_id"] == "m1"


@pytest.mark.asyncio
async def test_handle_bridge_message_voice_message_rewrites_content() -> None:
    ch = WhatsAppChannel(WhatsAppConfig(enabled=True), MessageBus())
    ch._handle_message = AsyncMock()  # type: ignore[method-assign]

    payload = {
        "type": "message",
        "sender": "lid_abc@lid.whatsapp.net",
        "content": "[Voice Message]",
    }

    await ch._handle_bridge_message(json.dumps(payload))

    kwargs = ch._handle_message.await_args.kwargs
    assert "Transcription not available" in kwargs["content"]


@pytest.mark.asyncio
async def test_handle_bridge_message_status_updates_connected_flag() -> None:
    ch = WhatsAppChannel(WhatsAppConfig(enabled=True), MessageBus())
    assert ch._connected is False

    await ch._handle_bridge_message(json.dumps({"type": "status", "status": "connected"}))
    assert ch._connected is True

    await ch._handle_bridge_message(json.dumps({"type": "status", "status": "disconnected"}))
    assert ch._connected is False


@pytest.mark.asyncio
async def test_handle_bridge_message_other_types_do_not_crash() -> None:
    ch = WhatsAppChannel(WhatsAppConfig(enabled=True), MessageBus())
    await ch._handle_bridge_message(json.dumps({"type": "qr"}))
    await ch._handle_bridge_message(json.dumps({"type": "error", "error": "boom"}))
