from __future__ import annotations

import asyncio
import sys
import types

import pytest

from hal.bus.events import InboundMessage
from hal.bus.queue import MessageBus
from hal.channels.base import BaseChannel
from hal.channels.manager import ChannelManager
from hal.infra.config.schema import Config


class _Cfg:
    def __init__(self, allow_from: list[str] | None = None):
        self.allow_from = allow_from or []


class DummyChannel(BaseChannel):
    name = "dummy"

    async def start(self) -> None:  # pragma: no cover
        raise AssertionError("not used")

    async def stop(self) -> None:  # pragma: no cover
        raise AssertionError("not used")

    async def send(self, msg) -> None:  # pragma: no cover
        raise AssertionError("not used")


def test_is_allowed_allows_everyone_when_allowlist_empty() -> None:
    ch = DummyChannel(_Cfg([]), MessageBus())
    assert ch.is_allowed("123") is True


def test_is_allowed_exact_match() -> None:
    ch = DummyChannel(_Cfg(["123"]), MessageBus())
    assert ch.is_allowed("123") is True
    assert ch.is_allowed("999") is False


def test_is_allowed_supports_pipe_separated_sender_ids() -> None:
    ch = DummyChannel(_Cfg(["alice"]), MessageBus())
    assert ch.is_allowed("42|alice") is True
    assert ch.is_allowed("42|bob") is False


@pytest.mark.asyncio
async def test_handle_message_publishes_inbound_when_allowed() -> None:
    bus = MessageBus()
    ch = DummyChannel(_Cfg([]), bus)

    await ch._handle_message(sender_id="u1", chat_id="c1", content="hello")

    assert bus.inbound_size == 1
    msg = await bus.consume_inbound()
    assert isinstance(msg, InboundMessage)
    assert msg.channel == "dummy"
    assert msg.sender_id == "u1"
    assert msg.chat_id == "c1"
    assert msg.content == "hello"
    assert msg.media == []
    assert msg.metadata == {}


@pytest.mark.asyncio
async def test_handle_message_denies_when_not_allowed() -> None:
    bus = MessageBus()
    ch = DummyChannel(_Cfg(["allowed"]), bus)

    await ch._handle_message(sender_id="denied", chat_id="c1", content="hello")
    assert bus.inbound_size == 0


def test_channel_manager_initializes_enabled_channels(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyTelegram(BaseChannel):
        name = "telegram"

        def __init__(self, config, bus, groq_api_key: str = "", memory_manager=None):
            super().__init__(config, bus)

        async def start(self) -> None:  # pragma: no cover
            pass

        async def stop(self) -> None:  # pragma: no cover
            pass

        async def send(self, msg) -> None:  # pragma: no cover
            pass

    tg_mod = types.ModuleType("hal.channels.telegram")
    tg_mod.TelegramChannel = DummyTelegram

    monkeypatch.setitem(sys.modules, "hal.channels.telegram", tg_mod)

    cfg = Config()
    cfg.channels.telegram.enabled = True

    mgr = ChannelManager(cfg, MessageBus())

    assert set(mgr.enabled_channels) == {"telegram"}


def test_channel_manager_skips_channel_when_import_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    tg_mod = types.ModuleType("hal.channels.telegram")
    monkeypatch.setitem(sys.modules, "hal.channels.telegram", tg_mod)

    cfg = Config()
    cfg.channels.telegram.enabled = True

    mgr = ChannelManager(cfg, MessageBus())
    assert mgr.get_channel("telegram") is None
    assert mgr.enabled_channels == []


@pytest.mark.asyncio
async def test_channel_manager_start_all_no_channels_returns() -> None:
    cfg = Config()  # all disabled
    mgr = ChannelManager(cfg, MessageBus())
    assert mgr.enabled_channels == []

    await mgr.start_all()  # should not raise


@pytest.mark.asyncio
async def test_channel_manager_start_and_stop_all(tmp_path) -> None:
    cfg = Config()
    bus = MessageBus()
    mgr = ChannelManager(cfg, bus)

    class Dummy(BaseChannel):
        name = "dummy"

        def __init__(self):
            super().__init__(config=None, bus=bus)
            self.start_calls = 0
            self.stop_calls = 0
            self.send_calls = 0

        async def start(self) -> None:
            self.start_calls += 1

        async def stop(self) -> None:
            self.stop_calls += 1

        async def send(self, msg) -> None:
            self.send_calls += 1

    mgr.channels = {"a": Dummy(), "b": Dummy()}

    await mgr.start_all()

    assert mgr.channels["a"].start_calls == 1
    assert mgr.channels["b"].start_calls == 1

    await mgr.stop_all()

    assert mgr.channels["a"].stop_calls == 1
    assert mgr.channels["b"].stop_calls == 1


@pytest.mark.asyncio
async def test_channel_manager_dispatch_outbound_routes_and_handles_unknown() -> None:
    cfg = Config()
    bus = MessageBus()
    mgr = ChannelManager(cfg, bus)

    class Dummy(BaseChannel):
        name = "telegram"

        def __init__(self):
            super().__init__(config=None, bus=bus)
            self.seen = []

        async def start(self) -> None:  # pragma: no cover
            pass

        async def stop(self) -> None:  # pragma: no cover
            pass

        async def send(self, msg) -> None:
            self.seen.append(msg)

    dummy = Dummy()
    mgr.channels = {"telegram": dummy}

    task = asyncio.create_task(mgr._dispatch_outbound())

    from hal.bus.events import OutboundMessage

    await bus.publish_outbound(OutboundMessage(channel="telegram", chat_id="1", content="ok"))

    for _ in range(50):
        if dummy.seen:
            break
        await asyncio.sleep(0)

    assert dummy.seen and dummy.seen[0].content == "ok"

    await bus.publish_outbound(OutboundMessage(channel="unknown", chat_id="1", content="x"))

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
