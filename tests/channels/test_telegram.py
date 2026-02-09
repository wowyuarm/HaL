from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from hal.bus.events import OutboundMessage
from hal.bus.queue import MessageBus
from hal.channels.telegram import TelegramChannel, _markdown_to_telegram_html
from hal.infra.config.schema import TelegramConfig


def test_markdown_to_telegram_html_converts_and_escapes() -> None:
    md = (
        "# Title\n"
        "> quote\n"
        "- item\n"
        "**bold** _italic_ ~~strike~~\n"
        "a & b < c > d\n"
        "`x<y&z`\n"
        "```\n<code>&\n```\n"
        "[link](https://example.com)\n"
        "some_var_name should_not_be_italic\n"
    )

    html = _markdown_to_telegram_html(md)

    # Headers and blockquotes become plain text
    assert "Title" in html
    assert "quote" in html

    # Basic formatting
    assert "<b>bold</b>" in html
    assert "<i>italic</i>" in html
    assert "<s>strike</s>" in html

    # Lists
    assert "• item" in html

    # HTML escaping
    assert "a &amp; b &lt; c &gt; d" in html

    # Code should be preserved and escaped
    assert "<code>x&lt;y&amp;z</code>" in html
    # Code blocks may retain trailing newlines from the source markdown
    assert "<pre><code>&lt;code&gt;&amp;" in html
    assert "</code></pre>" in html

    # Links
    assert '<a href="https://example.com">link</a>' in html


@pytest.mark.asyncio
async def test_send_returns_when_app_not_running() -> None:
    ch = TelegramChannel(TelegramConfig(enabled=True, token="t"), MessageBus())
    await ch.send(OutboundMessage(channel="telegram", chat_id="1", content="hi"))


@pytest.mark.asyncio
async def test_send_invalid_chat_id_is_ignored() -> None:
    class DummyBot:
        def __init__(self):
            self.sent: list[tuple[int, str, str | None]] = []

        async def send_message(self, chat_id: int, text: str, parse_mode: str | None = None) -> None:
            self.sent.append((chat_id, text, parse_mode))

    class DummyApp:
        def __init__(self):
            self.bot = DummyBot()

    ch = TelegramChannel(TelegramConfig(enabled=True, token="t"), MessageBus())
    ch._app = DummyApp()  # type: ignore[attr-defined]

    await ch.send(OutboundMessage(channel="telegram", chat_id="not-an-int", content="hi"))
    assert ch._app.bot.sent == []


@pytest.mark.asyncio
async def test_send_falls_back_to_plain_text_on_html_error() -> None:
    class DummyBot:
        def __init__(self):
            self.sent: list[tuple[int, str, str | None]] = []

        async def send_message(self, chat_id: int, text: str, parse_mode: str | None = None) -> None:
            # Simulate Telegram rejecting HTML
            if parse_mode == "HTML":
                raise RuntimeError("bad html")
            self.sent.append((chat_id, text, parse_mode))

    class DummyApp:
        def __init__(self):
            self.bot = DummyBot()

    ch = TelegramChannel(TelegramConfig(enabled=True, token="t"), MessageBus())
    ch._app = DummyApp()  # type: ignore[attr-defined]

    msg = OutboundMessage(channel="telegram", chat_id="123", content="**hi**")
    await ch.send(msg)

    # First attempt raised, second attempt should succeed without parse_mode.
    assert ch._app.bot.sent == [(123, "**hi**", None)]


def test_get_extension_prefers_mime_type_mapping() -> None:
    ch = TelegramChannel(TelegramConfig(enabled=True, token="t"), MessageBus())
    assert ch._get_extension("image", "image/png") == ".png"
    assert ch._get_extension("voice", "audio/ogg") == ".ogg"


def test_get_extension_falls_back_to_type_map() -> None:
    ch = TelegramChannel(TelegramConfig(enabled=True, token="t"), MessageBus())
    assert ch._get_extension("image", None) == ".jpg"
    assert ch._get_extension("voice", None) == ".ogg"
    assert ch._get_extension("audio", None) == ".mp3"
    assert ch._get_extension("file", None) == ""


class _User:
    def __init__(self, user_id: int, username: str | None = None, first_name: str = "U"):
        self.id = user_id
        self.username = username
        self.first_name = first_name


class _Chat:
    def __init__(self, type_: str):
        self.type = type_


class _Media:
    def __init__(self, file_id: str, mime_type: str | None = None):
        self.file_id = file_id
        self.mime_type = mime_type


class _Message:
    def __init__(
        self,
        chat_id: int,
        text: str | None = None,
        caption: str | None = None,
        photo: list[_Media] | None = None,
        voice: _Media | None = None,
        audio: _Media | None = None,
        document: _Media | None = None,
        chat_type: str = "private",
        message_id: int = 1,
    ):
        self.chat_id = chat_id
        self.text = text
        self.caption = caption
        self.photo = photo
        self.voice = voice
        self.audio = audio
        self.document = document
        self.chat = _Chat(chat_type)
        self.message_id = message_id


class _Update:
    def __init__(self, message: _Message | None, user: _User | None):
        self.message = message
        self.effective_user = user


@pytest.mark.asyncio
async def test_on_message_text_only_forwards_to_bus(tmp_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ch = TelegramChannel(TelegramConfig(enabled=True, token="t"), MessageBus())

    ch._start_typing = MagicMock()  # type: ignore[method-assign]
    ch._handle_message = AsyncMock()  # type: ignore[method-assign]

    update = _Update(message=_Message(chat_id=123, text="hello"), user=_User(7, username="alice"))

    await ch._on_message(update, context=None)  # type: ignore[arg-type]

    ch._start_typing.assert_called_once_with("123")
    ch._handle_message.assert_awaited_once()

    kwargs = ch._handle_message.await_args.kwargs
    assert kwargs["sender_id"].startswith("7|")
    assert kwargs["chat_id"] == "123"
    assert kwargs["content"] == "hello"
    assert kwargs["media"] == []


@pytest.mark.asyncio
async def test_on_message_photo_downloads_and_adds_media(tmp_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyFile:
        async def download_to_drive(self, path: str) -> None:
            Path(path).write_bytes(b"data")

    class DummyBot:
        async def get_file(self, file_id: str):
            return DummyFile()

    class DummyApp:
        def __init__(self):
            self.bot = DummyBot()

    ch = TelegramChannel(TelegramConfig(enabled=True, token="t"), MessageBus())
    ch._app = DummyApp()  # type: ignore[attr-defined]

    ch._start_typing = MagicMock()  # type: ignore[method-assign]
    ch._handle_message = AsyncMock()  # type: ignore[method-assign]

    update = _Update(
        message=_Message(
            chat_id=123,
            caption="cap",
            photo=[_Media(file_id="photo-file-id-0123456789")],
        ),
        user=_User(1),
    )

    await ch._on_message(update, context=None)  # type: ignore[arg-type]

    kwargs = ch._handle_message.await_args.kwargs
    assert "[image:" in kwargs["content"]
    assert "cap" in kwargs["content"]
    assert len(kwargs["media"]) == 1
    media_path = Path(kwargs["media"][0])
    assert media_path.exists()


@pytest.mark.asyncio
async def test_on_message_voice_transcribes_when_available(tmp_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyFile:
        async def download_to_drive(self, path: str) -> None:
            Path(path).write_bytes(b"data")

    class DummyBot:
        async def get_file(self, file_id: str):
            return DummyFile()

    class DummyApp:
        def __init__(self):
            self.bot = DummyBot()

    class DummyTranscriber:
        def __init__(self, api_key: str = ""):
            self.api_key = api_key

        async def transcribe(self, file_path):
            return "hello"

    monkeypatch.setattr(
        "hal.infra.providers.transcription.GroqTranscriptionProvider", DummyTranscriber
    )

    ch = TelegramChannel(TelegramConfig(enabled=True, token="t"), MessageBus(), groq_api_key="k")
    ch._app = DummyApp()  # type: ignore[attr-defined]

    ch._start_typing = MagicMock()  # type: ignore[method-assign]
    ch._handle_message = AsyncMock()  # type: ignore[method-assign]

    update = _Update(
        message=_Message(
            chat_id=123,
            voice=_Media(file_id="voice-file-id-0123456789", mime_type="audio/ogg"),
        ),
        user=_User(2),
    )

    await ch._on_message(update, context=None)  # type: ignore[arg-type]

    kwargs = ch._handle_message.await_args.kwargs
    assert "[transcription: hello]" in kwargs["content"]


@pytest.mark.asyncio
async def test_stop_cancels_typing_tasks_and_shuts_down_app() -> None:
    class DummyUpdater:
        def __init__(self):
            self.stop = AsyncMock()

    class DummyApp:
        def __init__(self):
            self.updater = DummyUpdater()
            self.stop = AsyncMock()
            self.shutdown = AsyncMock()

    ch = TelegramChannel(TelegramConfig(enabled=True, token="t"), MessageBus())
    ch._app = DummyApp()  # type: ignore[attr-defined]

    # Create a typing task
    t = asyncio.create_task(asyncio.sleep(10))
    ch._typing_tasks["123"] = t

    await ch.stop()

    assert ch._app is None
    assert ch._typing_tasks == {}
