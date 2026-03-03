from __future__ import annotations

import pytest

from hal.bus.events import Event, InboundMessage, OutboundMessage, ToolCallEvent
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
async def test_emit_fanout_and_type_matching() -> None:
    bus = MessageBus()
    calls: list[str] = []

    async def on_any(_event: Event) -> None:
        calls.append("any")

    async def on_tool_call(_event: Event) -> None:
        calls.append("tool")

    bus.subscribe(Event, on_any)
    bus.subscribe(ToolCallEvent, on_tool_call)

    event = ToolCallEvent(
        tool_name="fs",
        tool_id="t1",
        arguments={"action": "list"},
        result="ok",
        total_tool_calls=1,
        messages=[],
    )
    await bus.emit(event)

    assert calls == ["any", "tool"]


@pytest.mark.asyncio
async def test_unsubscribe_stops_handler_invocation() -> None:
    bus = MessageBus()
    calls = 0

    async def on_tool_call(_event: Event) -> None:
        nonlocal calls
        calls += 1

    bus.subscribe(ToolCallEvent, on_tool_call)
    bus.unsubscribe(ToolCallEvent, on_tool_call)

    await bus.emit(
        ToolCallEvent(
            tool_name="exec",
            tool_id="t2",
            arguments={"command": "pwd"},
            result="ok",
            total_tool_calls=1,
            messages=[],
        )
    )
    assert calls == 0


@pytest.mark.asyncio
async def test_emit_handler_failure_does_not_block_other_handlers() -> None:
    bus = MessageBus()
    calls: list[str] = []

    async def broken(_event: Event) -> None:
        raise RuntimeError("boom")

    async def healthy(_event: Event) -> None:
        calls.append("healthy")

    bus.subscribe(ToolCallEvent, broken)
    bus.subscribe(ToolCallEvent, healthy)

    await bus.emit(
        ToolCallEvent(
            tool_name="web_search",
            tool_id="t3",
            arguments={"query": "x"},
            result="ok",
            total_tool_calls=1,
            messages=[],
        )
    )
    assert calls == ["healthy"]
