from __future__ import annotations

import asyncio

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


@pytest.mark.asyncio
async def test_dispatch_outbound_delivers_to_subscribers_and_handles_errors() -> None:
    bus = MessageBus()

    seen: list[OutboundMessage] = []
    done = asyncio.Event()

    async def bad(_msg: OutboundMessage) -> None:
        raise RuntimeError("boom")

    async def good(msg: OutboundMessage) -> None:
        seen.append(msg)
        done.set()

    bus.subscribe_outbound("telegram", bad)
    bus.subscribe_outbound("telegram", good)

    task = asyncio.create_task(bus.dispatch_outbound())

    await bus.publish_outbound(OutboundMessage(channel="telegram", chat_id="1", content="ok"))

    await asyncio.wait_for(done.wait(), timeout=1.0)

    bus.stop()
    # dispatch_outbound waits up to 1.0s in its internal wait_for(); give it headroom to exit.
    await asyncio.wait_for(task, timeout=2.0)

    assert len(seen) == 1
    assert seen[0].content == "ok"


def test_subscribe_outbound_registers_multiple_callbacks() -> None:
    bus = MessageBus()

    async def cb1(_msg: OutboundMessage) -> None:  # pragma: no cover
        return None

    async def cb2(_msg: OutboundMessage) -> None:  # pragma: no cover
        return None

    bus.subscribe_outbound("x", cb1)
    bus.subscribe_outbound("x", cb2)

    assert "x" in bus._outbound_subscribers
    assert bus._outbound_subscribers["x"] == [cb1, cb2]
