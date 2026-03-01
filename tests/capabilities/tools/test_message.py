from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from hal.bus.events import OutboundMessage
from hal.capabilities.tools.message import MessageTool


@pytest.mark.asyncio
async def test_message_tool_requires_target_context() -> None:
    tool = MessageTool(send_callback=AsyncMock())
    out = await tool.execute(content="hi")
    assert "No target" in out


@pytest.mark.asyncio
async def test_message_tool_requires_send_callback() -> None:
    tool = MessageTool(send_callback=None, default_channel="cli", default_chat_id="direct")
    out = await tool.execute(content="hi")
    assert "not configured" in out


@pytest.mark.asyncio
async def test_message_tool_sends_with_defaults_and_explicit_overrides() -> None:
    cb = AsyncMock()
    tool = MessageTool(send_callback=cb, default_channel="cli", default_chat_id="direct")

    out = await tool.execute(content="hi")
    assert out == "Message sent to cli:direct"
    cb.assert_awaited_once_with(OutboundMessage(channel="cli", chat_id="direct", content="hi"))

    cb.reset_mock()
    out2 = await tool.execute(content="yo", channel="telegram", chat_id="123")
    assert out2 == "Message sent to telegram:123"
    cb.assert_awaited_once_with(OutboundMessage(channel="telegram", chat_id="123", content="yo"))


@pytest.mark.asyncio
async def test_message_tool_handles_callback_error() -> None:
    async def boom(_msg: OutboundMessage) -> None:
        raise RuntimeError("fail")

    tool = MessageTool(send_callback=boom, default_channel="cli", default_chat_id="direct")
    out = await tool.execute(content="hi")
    assert out.startswith("Error sending message")


def test_message_tool_setters_update_context_and_callback() -> None:
    tool = MessageTool(send_callback=None)
    tool.set_context("x", "y")

    assert tool._default_channel == "x"
    assert tool._default_chat_id == "y"
    # set_context also resets sent_in_turn
    assert tool.sent_in_turn is False

    cb = AsyncMock()
    tool.set_send_callback(cb)
    assert tool._send_callback is cb


# --- sent_in_turn flag tests ---


@pytest.mark.asyncio
async def test_sent_in_turn_set_on_successful_send() -> None:
    tool = MessageTool(send_callback=AsyncMock(), default_channel="tg", default_chat_id="1")
    assert tool.sent_in_turn is False

    await tool.execute(content="hello")
    assert tool.sent_in_turn is True


@pytest.mark.asyncio
async def test_sent_in_turn_not_set_on_failed_send() -> None:
    async def boom(_msg: OutboundMessage) -> None:
        raise RuntimeError("fail")

    tool = MessageTool(send_callback=boom, default_channel="tg", default_chat_id="1")
    await tool.execute(content="hello")
    assert tool.sent_in_turn is False


@pytest.mark.asyncio
async def test_sent_in_turn_reset_by_set_context() -> None:
    tool = MessageTool(send_callback=AsyncMock(), default_channel="tg", default_chat_id="1")
    await tool.execute(content="hello")
    assert tool.sent_in_turn is True

    tool.set_context("tg", "1")
    assert tool.sent_in_turn is False
