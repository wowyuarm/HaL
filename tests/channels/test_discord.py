from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from hal.bus.events import OutboundMessage
from hal.bus.queue import MessageBus
from hal.channels.discord import DiscordChannel
from hal.infra.config.schema import DiscordConfig


class _Resp:
    def __init__(self, status_code: int, json_data: dict | None = None):
        self.status_code = status_code
        self._json = json_data or {}

    def json(self) -> dict:
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400 and self.status_code != 429:
            raise RuntimeError(f"http {self.status_code}")


class _HTTP:
    def __init__(self, responses: list[_Resp]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def post(self, url: str, headers: dict | None = None, json: dict | None = None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return self._responses.pop(0)

    async def get(self, url: str):
        # Minimal response for attachment downloads
        class R:
            status_code = 200
            content = b"data"

            def raise_for_status(self):
                return None

        return R()


@pytest.mark.asyncio
async def test_send_retries_on_rate_limit_and_includes_reply_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = DiscordConfig(enabled=True, token="t")
    ch = DiscordChannel(cfg, MessageBus())

    ch._http = _HTTP([
        _Resp(429, {"retry_after": 0.0}),
        _Resp(200),
    ])

    # Avoid real sleep + typing stop side effects
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    ch._stop_typing = AsyncMock()  # type: ignore[method-assign]

    msg = OutboundMessage(channel="discord", chat_id="123", content="hi", reply_to="m0")
    await ch.send(msg)

    assert len(ch._http.calls) == 2
    payload = ch._http.calls[-1]["json"]
    assert payload["content"] == "hi"
    assert payload["message_reference"] == {"message_id": "m0"}
    assert payload["allowed_mentions"] == {"replied_user": False}


@pytest.mark.asyncio
async def test_handle_message_create_downloads_attachment_and_forwards(tmp_home, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = DiscordConfig(enabled=True, token="t")
    ch = DiscordChannel(cfg, MessageBus())

    # Provide fake HTTP client with get()
    ch._http = _HTTP([_Resp(200)])

    ch._start_typing = AsyncMock()  # type: ignore[method-assign]
    ch._handle_message = AsyncMock()  # type: ignore[method-assign]

    payload = {
        "id": "m1",
        "guild_id": "g1",
        "channel_id": "c1",
        "content": "hello",
        "author": {"id": "u1", "bot": False},
        "attachments": [
            {
                "id": "att1",
                "url": "https://example.com/a.txt",
                "filename": "a.txt",
                "size": 1,
            }
        ],
        "referenced_message": {"id": "m0"},
    }

    await ch._handle_message_create(payload)

    ch._start_typing.assert_awaited_once_with("c1")
    ch._handle_message.assert_awaited_once()

    kwargs = ch._handle_message.await_args.kwargs
    assert kwargs["sender_id"] == "u1"
    assert kwargs["chat_id"] == "c1"
    assert "hello" in kwargs["content"]
    assert "[attachment:" in kwargs["content"]
    assert kwargs["media"], "expected downloaded attachment path"
    assert kwargs["metadata"]["message_id"] == "m1"
    assert kwargs["metadata"]["guild_id"] == "g1"
    assert kwargs["metadata"]["reply_to"] == "m0"


@pytest.mark.asyncio
async def test_handle_message_create_ignores_bot_messages() -> None:
    ch = DiscordChannel(DiscordConfig(enabled=True, token="t"), MessageBus())
    ch._handle_message = AsyncMock()  # type: ignore[method-assign]

    await ch._handle_message_create({"author": {"bot": True}})
    ch._handle_message.assert_not_called()


class _WS:
    def __init__(self, frames: list[str]):
        self._frames = list(frames)
        self.sent: list[str] = []

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._frames:
            raise StopAsyncIteration
        return self._frames.pop(0)

    async def send(self, payload: str) -> None:
        self.sent.append(payload)


@pytest.mark.asyncio
async def test_identify_sends_token_and_intents() -> None:
    cfg = DiscordConfig(enabled=True, token="t", intents=123)
    ch = DiscordChannel(cfg, MessageBus())

    ws = _WS([])
    ch._ws = ws  # type: ignore[assignment]

    await ch._identify()

    assert ws.sent, "expected IDENTIFY payload"
    data = json.loads(ws.sent[0])
    assert data["op"] == 2
    assert data["d"]["token"] == "t"
    assert data["d"]["intents"] == 123


@pytest.mark.asyncio
async def test_gateway_loop_handles_hello_message_create_and_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = DiscordConfig(enabled=True, token="t")
    ch = DiscordChannel(cfg, MessageBus())

    hello = json.dumps({"op": 10, "d": {"heartbeat_interval": 1000}})
    msg = json.dumps({"op": 0, "t": "MESSAGE_CREATE", "d": {"id": "m"}})
    reconnect = json.dumps({"op": 7})

    ch._ws = _WS([
        "not json",
        hello,
        msg,
        reconnect,
    ])  # type: ignore[assignment]

    ch._start_heartbeat = AsyncMock()  # type: ignore[method-assign]
    ch._identify = AsyncMock()  # type: ignore[method-assign]
    ch._handle_message_create = AsyncMock()  # type: ignore[method-assign]

    await ch._gateway_loop()

    ch._start_heartbeat.assert_awaited_once()
    ch._identify.assert_awaited_once()
    ch._handle_message_create.assert_awaited_once_with({"id": "m"})


@pytest.mark.asyncio
async def test_start_heartbeat_sends_once_and_cancels_previous(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = DiscordConfig(enabled=True, token="t")
    ch = DiscordChannel(cfg, MessageBus())

    ws = _WS([])
    ws.send = AsyncMock()  # type: ignore[method-assign]
    ch._ws = ws  # type: ignore[assignment]

    ch._running = True
    ch._seq = 99

    # Existing heartbeat task should be cancelled
    old = asyncio.create_task(asyncio.sleep(10))
    ch._heartbeat_task = old

    real_sleep = asyncio.sleep

    async def fake_sleep(_s: float):
        # Stop after first heartbeat
        ch._running = False

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    await ch._start_heartbeat(interval_s=0.0)

    # Let the event loop process the cancellation of the previous task.
    await real_sleep(0)
    with pytest.raises(asyncio.CancelledError):
        await old

    # New task should run and send at least once
    assert ch._heartbeat_task is not None
    await asyncio.wait_for(ch._heartbeat_task, timeout=1.0)

    ws.send.assert_awaited()
    sent = json.loads(ws.send.await_args.args[0])
    assert sent["op"] == 1
    assert sent["d"] == 99
