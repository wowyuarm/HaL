from __future__ import annotations

import pytest

from hal.bus.events import InboundMessage, OutboundMessage
from hal.bus.queue import MessageBus


@pytest.mark.asyncio
async def test_inbound_publish_and_consume_and_size() -> None:
    bus = MessageBus()
    assert bus.inbound_size == 0

    msg = InboundMessage(channel="cli", sender_id="u", chat_id="c", content="hi")
    await bus.publish_inbound(msg)
    assert bus.inbound_size == 1

    got = await bus.consume_inbound()
    assert got is msg
    assert bus.inbound_size == 0


@pytest.mark.asyncio
async def test_outbound_publish_and_consume_and_size() -> None:
    bus = MessageBus()
    assert bus.outbound_size == 0

    msg = OutboundMessage(channel="telegram", chat_id="1", content="hello")
    await bus.publish_outbound(msg)
    assert bus.outbound_size == 1

    got = await bus.consume_outbound()
    assert got is msg
    assert bus.outbound_size == 0
