from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from hal.bus.events import OutboundMessage
from hal.bus.queue import MessageBus
from hal.channels.telegram import TelegramChannel, _markdown_to_telegram_html
from hal.infra.config.schema import TelegramConfig


def test_split_telegram_message_no_split() -> None:
    ch = TelegramChannel(TelegramConfig(enabled=True, token="t"), MessageBus())
    text = "hello"
    assert ch._split_telegram_message(text) == [text]


def test_split_telegram_message_long_text() -> None:
    ch = TelegramChannel(TelegramConfig(enabled=True, token="t"), MessageBus())
    text = "a" * 9001
    chunks = ch._split_telegram_message(text, max_length=4000)

    assert len(chunks) == 3
    assert all(len(c) <= 4000 for c in chunks)
    assert "".join(chunks) == text


def test_split_telegram_message_prefers_newline_then_space() -> None:
    ch = TelegramChannel(TelegramConfig(enabled=True, token="t"), MessageBus())

    text_with_newline = "a" * 50 + "\n" + "b" * 50
    chunks_newline = ch._split_telegram_message(text_with_newline, max_length=60)
    assert chunks_newline == ["a" * 50, "b" * 50]

    text_with_space = "a" * 50 + " " + "b" * 50
    chunks_space = ch._split_telegram_message(text_with_space, max_length=60)
    assert chunks_space == ["a" * 50, "b" * 50]


def test_compress_context_output_respects_max_chars() -> None:
    text = "abcdefghij" * 100
    out = TelegramChannel._compress_context_output(text, max_chars=120)
    assert len(out) <= 120
    assert "omitted" in out


def test_format_context_report_compacts_system_prompt_by_default() -> None:
    ch = TelegramChannel(TelegramConfig(enabled=True, token="t"), MessageBus())
    report = ch._format_context_report(
        {
            "channel": "telegram",
            "chat_id": "1",
            "model": "test-model",
            "mode": "collab",
            "history_message_count": 1,
            "history_chars": 12,
            "recall_count": 0,
            "system_prompt_chars": 5000,
            "total_input_chars": 5200,
            "token_estimate": {
                "method": "chars_div_4",
                "messages_only": 1000,
                "with_tools": 1200,
                "tools_only": 200,
            },
            "history_config": {
                "history_days": 1,
                "max_messages": 50,
                "max_history_chars": 0,
                "recent_full_turns": 3,
                "assistant_truncate_chars": 200,
            },
            "history_window": [{"date": "2026-02-22", "exists": True}],
            "messages": [
                {"role": "system", "content": "S" * 4000},
                {"role": "user", "content": "hello"},
            ],
        },
        "[context inspection]",
    )
    assert "(system prompt compressed, sha1=" in report
    assert "[0] role=system chars=4000" in report


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

        async def send_message(
            self, chat_id: int, text: str, parse_mode: str | None = None
        ) -> None:
            self.sent.append((chat_id, text, parse_mode))

    class DummyApp:
        def __init__(self):
            self.bot = DummyBot()

    ch = TelegramChannel(TelegramConfig(enabled=True, token="t"), MessageBus())
    ch._app = DummyApp()  # type: ignore[attr-defined]

    await ch.send(OutboundMessage(channel="telegram", chat_id="not-an-int", content="hi"))
    assert ch._app.bot.sent == []


@pytest.mark.asyncio
async def test_send_falls_back_to_plain_text_on_single_chunk_html_error() -> None:
    class DummyBot:
        def __init__(self):
            self.sent: list[tuple[int, str, str | None]] = []
            self.html_calls = 0

        async def send_message(
            self, chat_id: int, text: str, parse_mode: str | None = None
        ) -> None:
            if parse_mode == "HTML":
                self.html_calls += 1
                if self.html_calls == 1:
                    raise RuntimeError("bad html")
            self.sent.append((chat_id, text, parse_mode))

    class DummyApp:
        def __init__(self):
            self.bot = DummyBot()

    ch = TelegramChannel(TelegramConfig(enabled=True, token="t"), MessageBus())
    ch._app = DummyApp()  # type: ignore[attr-defined]

    msg = OutboundMessage(channel="telegram", chat_id="123", content="**hi**")
    await ch.send(msg)

    assert ch._app.bot.sent == [(123, "**hi**", None)]


@pytest.mark.asyncio
async def test_send_multiple_chunks_calls_send_message_multiple_times() -> None:
    class DummyBot:
        def __init__(self):
            self.sent: list[tuple[int, str, str | None]] = []

        async def send_message(
            self, chat_id: int, text: str, parse_mode: str | None = None
        ) -> None:
            self.sent.append((chat_id, text, parse_mode))

    class DummyApp:
        def __init__(self):
            self.bot = DummyBot()

    ch = TelegramChannel(TelegramConfig(enabled=True, token="t"), MessageBus())
    ch._app = DummyApp()  # type: ignore[attr-defined]

    msg = OutboundMessage(channel="telegram", chat_id="123", content=("a" * 4100))
    await ch.send(msg)

    assert len(ch._app.bot.sent) == 2
    assert all(item[2] == "HTML" for item in ch._app.bot.sent)


def test_split_then_html_keeps_tags_complete_per_chunk() -> None:
    ch = TelegramChannel(TelegramConfig(enabled=True, token="t"), MessageBus())

    md = "**bold** " * 700
    chunks = ch._split_telegram_message(md, max_length=4000)
    html_chunks = [_markdown_to_telegram_html(chunk) for chunk in chunks]

    assert len(html_chunks) >= 2
    for html in html_chunks:
        assert html.count("<b>") == html.count("</b>")
        assert html.count("<i>") == html.count("</i>")
        assert html.count("<s>") == html.count("</s>")


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
async def test_on_message_text_only_forwards_to_bus(
    tmp_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
async def test_on_message_photo_downloads_and_adds_media(
    tmp_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
async def test_on_message_voice_transcribes_when_available(
    tmp_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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


@pytest.mark.asyncio
async def test_on_reset_clears_history_without_session_key() -> None:
    memory = MagicMock()
    ch = TelegramChannel(TelegramConfig(enabled=True, token="t"), MessageBus(), memory_manager=memory)

    msg = _Message(chat_id=123, text="/reset")
    msg.reply_text = AsyncMock()  # type: ignore[attr-defined]
    update = _Update(message=msg, user=_User(1))

    await ch._on_reset(update, context=None)  # type: ignore[arg-type]

    memory.clear_conversation_history.assert_called_once_with(channel="telegram", chat_id="123")
    msg.reply_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_on_context_without_inspector_replies_warning() -> None:
    ch = TelegramChannel(TelegramConfig(enabled=True, token="t"), MessageBus())

    msg = _Message(chat_id=123, text="/context")
    msg.reply_text = AsyncMock()  # type: ignore[attr-defined]
    update = _Update(message=msg, user=_User(1))

    await ch._on_context(update, context=None)  # type: ignore[arg-type]

    msg.reply_text.assert_awaited_once()
    assert "not configured" in msg.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_on_context_uses_inspector_and_sends_report() -> None:
    inspector = AsyncMock(
        return_value={
            "channel": "telegram",
            "chat_id": "123",
            "model": "test-model",
            "mode": "collab",
            "history_message_count": 2,
            "history_chars": 10,
            "recall_count": 1,
            "system_prompt_chars": 20,
            "total_input_chars": 30,
            "token_estimate": {
                "method": "litellm.token_counter",
                "messages_only": 11,
                "with_tools": 22,
                "tools_only": 11,
            },
            "history_config": {
                "history_days": 1,
                "max_messages": 50,
                "max_history_chars": 0,
                "recent_full_turns": 3,
                "assistant_truncate_chars": 200,
            },
            "history_window": [{"date": "2026-02-22", "exists": True}],
            "latest_metrics": {
                "timestamp": "2026-02-22T10:00:00",
                "first_prompt_tokens": 100,
                "first_completion_tokens": 20,
                "first_total_tokens": 120,
                "loop_iterations": 2,
                "tools_used": ["fs"],
                "spawn_total_tokens": 0,
            },
            "messages": [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "hi"},
            ],
        }
    )
    ch = TelegramChannel(
        TelegramConfig(enabled=True, token="t"),
        MessageBus(),
        context_inspector=inspector,
    )

    msg = _Message(chat_id=123, text="/context ping")
    msg.reply_text = AsyncMock()  # type: ignore[attr-defined]
    update = _Update(message=msg, user=_User(1))

    await ch._on_context(update, context=None)  # type: ignore[arg-type]

    inspector.assert_awaited_once_with(
        channel="telegram",
        chat_id="123",
        current_message="ping",
    )
    assert msg.reply_text.await_count >= 1
    first_chunk = msg.reply_text.await_args_list[0].args[0]
    assert "HaL Context Inspector" in first_chunk
    assert "Token Estimate" in first_chunk


@pytest.mark.asyncio
async def test_on_context_full_mode_parses_message() -> None:
    inspector = AsyncMock(
        return_value={
            "channel": "telegram",
            "chat_id": "123",
            "model": "test-model",
            "mode": "collab",
            "history_message_count": 0,
            "history_chars": 0,
            "recall_count": 0,
            "system_prompt_chars": 3,
            "total_input_chars": 5,
            "token_estimate": {
                "method": "chars_div_4",
                "messages_only": 1,
                "with_tools": 1,
                "tools_only": 0,
            },
            "history_config": {
                "history_days": 1,
                "max_messages": 50,
                "max_history_chars": 0,
                "recent_full_turns": 3,
                "assistant_truncate_chars": 200,
            },
            "history_window": [{"date": "2026-02-22", "exists": True}],
            "messages": [{"role": "system", "content": "sys"}],
        }
    )
    ch = TelegramChannel(
        TelegramConfig(enabled=True, token="t"),
        MessageBus(),
        context_inspector=inspector,
    )

    msg = _Message(chat_id=123, text="/context full ping")
    msg.reply_text = AsyncMock()  # type: ignore[attr-defined]
    update = _Update(message=msg, user=_User(1))

    await ch._on_context(update, context=None)  # type: ignore[arg-type]

    inspector.assert_awaited_once_with(
        channel="telegram",
        chat_id="123",
        current_message="ping",
    )
    first_chunk = msg.reply_text.await_args_list[0].args[0]
    assert "view: full" in first_chunk


@pytest.mark.asyncio
async def test_on_context_denies_disallowed_sender() -> None:
    inspector = AsyncMock(return_value={})
    cfg = TelegramConfig(enabled=True, token="t", allow_from=["42"])
    ch = TelegramChannel(cfg, MessageBus(), context_inspector=inspector)

    msg = _Message(chat_id=123, text="/context hello")
    msg.reply_text = AsyncMock()  # type: ignore[attr-defined]
    update = _Update(message=msg, user=_User(1))

    await ch._on_context(update, context=None)  # type: ignore[arg-type]

    inspector.assert_not_awaited()
    msg.reply_text.assert_awaited_once()
    assert "not allowed" in msg.reply_text.await_args.args[0].lower()
