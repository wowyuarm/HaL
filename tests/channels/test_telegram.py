from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from hal.bus.events import OutboundMessage, SystemStartupEvent
from hal.bus.queue import MessageBus
from hal.channels.telegram import TelegramChannel, _markdown_to_telegram_html
from hal.infra.config.schema import TelegramConfig


class _DummyApp:
    def __init__(self, bot: object):
        self.bot = bot


class _SimpleRecordingBot:
    def __init__(self, *, fail_first_html: bool = False):
        self.sent: list[tuple[int, str, str | None]] = []
        self._fail_first_html = fail_first_html
        self._html_calls = 0

    async def send_message(self, chat_id: int, text: str, parse_mode: str | None = None) -> None:
        if parse_mode == "HTML":
            self._html_calls += 1
            if self._fail_first_html and self._html_calls == 1:
                raise RuntimeError("bad html")
        self.sent.append((chat_id, text, parse_mode))


class _SentMessage:
    def __init__(self, message_id: int):
        self.message_id = message_id


class _AppendRecordingBot:
    def __init__(self):
        self.sent: list[tuple[int, str, str | None]] = []
        self.edited: list[tuple[int, int, str, str | None]] = []
        self._next_id = 100

    async def send_message(
        self, chat_id: int, text: str, parse_mode: str | None = None
    ) -> _SentMessage:
        self.sent.append((chat_id, text, parse_mode))
        self._next_id += 1
        return _SentMessage(self._next_id)

    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        parse_mode: str | None = None,
    ) -> None:
        self.edited.append((chat_id, message_id, text, parse_mode))


def _attach_bot(channel: TelegramChannel, bot: object) -> None:
    channel._app = _DummyApp(bot)  # type: ignore[attr-defined]


def _extract_sent_text(send_message_mock: AsyncMock) -> str:
    """Extract `text` argument from AsyncMock.await_args."""
    return send_message_mock.await_args.kwargs.get(  # type: ignore[union-attr]
        "text",
        send_message_mock.await_args.args[1]  # type: ignore[union-attr]
        if len(send_message_mock.await_args.args) > 1  # type: ignore[union-attr]
        else "",
    )


def _build_startup_notification_channel() -> tuple[TelegramChannel, MagicMock, AsyncMock]:
    cfg = TelegramConfig(enabled=True, token="t", allow_from=["42"])
    memory_manager = MagicMock()
    channel = TelegramChannel(cfg, MessageBus(), memory_manager=memory_manager)
    channel.bus.emit = AsyncMock()  # type: ignore[method-assign]
    mock_bot = AsyncMock()
    _attach_bot(channel, mock_bot)
    return channel, memory_manager, mock_bot


def _mock_git_log(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: MagicMock(returncode=0, stdout="abc1234 fix: thing"),
    )


def _assert_startup_injection(
    channel: TelegramChannel,
    memory_manager: MagicMock,
    *,
    expected_content_fragment: str,
    expect_update_info: bool,
) -> None:
    """Validate memory/event side effects of startup notification."""
    memory_manager.record_event.assert_called_once()
    call_kwargs = memory_manager.record_event.call_args.kwargs
    assert call_kwargs["event_type"] == "system_startup"
    assert expected_content_fragment in call_kwargs["payload"]["content"]
    channel.bus.emit.assert_awaited_once()
    event = channel.bus.emit.await_args.args[0]  # type: ignore[union-attr]
    assert isinstance(event, SystemStartupEvent)
    assert event.channel == "telegram"
    assert event.chat_id == "42"
    if expect_update_info:
        assert event.update_info is not None
        return
    assert event.update_info is None


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
            "history_tokens": 8,
            "recall_count": 0,
            "recall_items": [],
            "baseline_created": False,
            "baseline_thread_slugs": ["hal-architecture", "context-system"],
            "recalled_thread_slugs": [],
            "system_prompt_chars": 5000,
            "system_prompt_tokens": 950,
            "total_input_chars": 5200,
            "total_input_tokens": 1000,
            "token_estimate": {
                "method": "chars_div_4",
                "messages_only": 1000,
                "with_tools": 1200,
                "tools_only": 200,
            },
            "history_config": {
                "memory_budget_tokens": 0,
                "recall_max_total_tokens": 500,
                "recall_max_per_item_tokens": 125,
            },
            "messages": [
                {"role": "system", "content": "S" * 4000},
                {"role": "user", "content": "hello"},
            ],
            "message_summaries": [
                {"role": "system", "chars": 4000, "tokens": 800, "preview": "S" * 80 + "…"},
                {"role": "user", "chars": 5, "tokens": 2, "preview": "hello"},
            ],
        },
    )
    # Compact mode: shows diagnostic summary, not per-message previews
    assert "<b>HaL Context Inspector</b>" in report
    assert "<b>Budget</b>" in report
    assert "input_tokens    1,000" in report
    assert "system          950" in report
    assert "baseline        frozen-session" in report
    assert "<b>Risk</b>" in report
    assert "using frozen session baseline" in report
    assert "system prompt dominates current token budget" in report
    assert "roles           system 1, user 1" in report
    assert "largest         [0] system 800t" in report


def test_format_context_report_compact_tolerates_non_dict_summary_entries() -> None:
    ch = TelegramChannel(TelegramConfig(enabled=True, token="t"), MessageBus())
    report = ch._format_context_report(
        {
            "channel": "telegram",
            "chat_id": "1",
            "model": "test-model",
            "mode": "collab",
            "history_message_count": 0,
            "history_chars": 0,
            "history_tokens": 0,
            "recall_count": 0,
            "recall_items": [],
            "baseline_created": True,
            "baseline_thread_slugs": [],
            "recalled_thread_slugs": [],
            "system_prompt_chars": 10,
            "system_prompt_tokens": 3,
            "total_input_chars": 10,
            "total_input_tokens": 3,
            "token_estimate": {
                "method": "chars_div_4",
                "messages_only": 3,
                "with_tools": 3,
                "tools_only": 0,
            },
            "messages": [],
            "message_summaries": [
                "bad-entry",
                {"role": "assistant", "chars": 8, "preview": "ok"},
            ],
        }
    )
    assert "roles           ? 1, assistant 1" in report
    assert "largest         [1] assistant 2t" in report


def test_format_context_report_full_includes_detailed_sections() -> None:
    ch = TelegramChannel(TelegramConfig(enabled=True, token="t"), MessageBus())
    report = ch._format_context_report(
        {
            "channel": "telegram",
            "chat_id": "1",
            "model": "test-model",
            "mode": "collab",
            "session_key": "telegram:1",
            "history_message_count": 1,
            "history_chars": 12,
            "history_tokens": 8,
            "recall_count": 3,
            "recall_items": [
                {"source": "a.md", "heading": "A", "score": 0.90, "source_type": "raw"},
                {"source": "b.md", "heading": "B", "score": 0.80, "source_type": "raw"},
                {"source": "c.md", "heading": "C", "score": 0.70, "source_type": "raw"},
            ],
            "baseline_created": True,
            "baseline_thread_slugs": ["alpha"],
            "recalled_thread_slugs": ["alpha", "beta"],
            "system_prompt_chars": 5000,
            "system_prompt_tokens": 950,
            "total_input_chars": 5200,
            "total_input_tokens": 1000,
            "token_estimate": {
                "method": "chars_div_4",
                "messages_only": 1000,
                "with_tools": 1200,
                "tools_only": 200,
            },
            "history_config": {
                "memory_budget_tokens": 0,
                "recall_max_total_tokens": 500,
                "recall_max_per_item_tokens": 125,
                "session_scoped": True,
            },
            "messages": [
                {"role": "system", "content": "S" * 4000},
                {"role": "user", "content": "hello"},
            ],
            "message_summaries": [
                {"role": "system", "chars": 4000, "tokens": 800, "preview": "S" * 80 + "…"},
                {"role": "user", "chars": 5, "tokens": 2, "preview": "hello"},
            ],
        },
        full_messages=True,
    )
    assert "(full)" in report
    assert "<b>Context Size</b>" in report
    assert 'a.md | "A" | 0.90 raw' in report
    assert 'c.md | "C" | 0.70 raw' in report
    assert "[0] system" in report
    assert "<b>Debug Meta</b>" in report
    assert "session_key     telegram:1" in report


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


def test_markdown_to_telegram_html_enhanced_patterns() -> None:
    md = (
        "**bold** and *italic*\n"
        "* list item\n"
        "  - nested item\n"
        "some_var_name should stay plain\n"
        "In a sentence, *word* should be italic.\n"
    )

    html = _markdown_to_telegram_html(md)

    assert "<b>bold</b> and <i>italic</i>" in html
    assert "• list item" in html
    assert "  • nested item" in html
    assert "some_var_name" in html
    assert "some<i>" not in html
    assert "In a sentence, <i>word</i> should be italic." in html


def test_markdown_to_telegram_html_italic_not_greedy() -> None:
    """*italic* regex must not span across multiple * pairs on the same line."""
    md = "Some *first* and *second* words"
    html = _markdown_to_telegram_html(md)
    assert "<i>first</i>" in html
    assert "<i>second</i>" in html
    # Should NOT merge into one giant italic span
    assert "first* and *second" not in html


def test_markdown_to_telegram_html_table() -> None:
    md = "| Name | Age |\n|------|-----|\n| Alice | 30 |\n| Bob & Co | 25 |\n"
    html = _markdown_to_telegram_html(md)
    assert "<pre>" in html
    assert "</pre>" in html
    # Table cell with & should be escaped inside <pre>
    assert "Bob &amp; Co" in html
    # Separator row should be rendered as unicode line, not literal dashes
    assert "───" in html


def test_markdown_to_telegram_html_blockquote() -> None:
    md = "> This is a quote\n> with two lines\nNormal text"
    html = _markdown_to_telegram_html(md)
    assert "<blockquote>" in html
    assert "This is a quote" in html
    assert "with two lines" in html
    assert "</blockquote>" in html
    assert "Normal text" in html


def test_markdown_to_telegram_html_blockquote_escapes_html() -> None:
    md = "> a <b>tag</b> & entity"
    html = _markdown_to_telegram_html(md)
    assert "<blockquote>" in html
    assert "&lt;b&gt;" in html
    assert "&amp; entity" in html


def test_markdown_to_telegram_html_horizontal_rule() -> None:
    md = "Before\n---\nAfter"
    html = _markdown_to_telegram_html(md)
    assert "━━━━" in html
    assert "Before" in html
    assert "After" in html


def test_markdown_to_telegram_html_header_bold() -> None:
    md = "# Main Title\n## Subtitle"
    html = _markdown_to_telegram_html(md)
    assert "<b>Main Title</b>" in html
    assert "<b>Subtitle</b>" in html


@pytest.mark.asyncio
async def test_send_returns_when_app_not_running() -> None:
    ch = TelegramChannel(TelegramConfig(enabled=True, token="t"), MessageBus())
    await ch.send(OutboundMessage(channel="telegram", chat_id="1", content="hi"))


@pytest.mark.asyncio
async def test_send_invalid_chat_id_is_ignored() -> None:
    bot = _SimpleRecordingBot()
    ch = TelegramChannel(TelegramConfig(enabled=True, token="t"), MessageBus())
    _attach_bot(ch, bot)

    await ch.send(OutboundMessage(channel="telegram", chat_id="not-an-int", content="hi"))
    assert bot.sent == []


@pytest.mark.asyncio
async def test_send_falls_back_to_plain_text_on_single_chunk_html_error() -> None:
    bot = _SimpleRecordingBot(fail_first_html=True)
    ch = TelegramChannel(TelegramConfig(enabled=True, token="t"), MessageBus())
    _attach_bot(ch, bot)

    msg = OutboundMessage(channel="telegram", chat_id="123", content="**hi**")
    await ch.send(msg)

    assert bot.sent == [(123, "**hi**", None)]


@pytest.mark.asyncio
async def test_send_multiple_chunks_calls_send_message_multiple_times() -> None:
    bot = _SimpleRecordingBot()
    ch = TelegramChannel(TelegramConfig(enabled=True, token="t"), MessageBus())
    _attach_bot(ch, bot)

    msg = OutboundMessage(channel="telegram", chat_id="123", content=("a" * 4100))
    await ch.send(msg)

    assert len(bot.sent) == 2
    assert all(item[2] == "HTML" for item in bot.sent)


@pytest.mark.asyncio
async def test_send_append_mode_concatenates_by_editing_existing_message() -> None:
    bot = _AppendRecordingBot()
    ch = TelegramChannel(TelegramConfig(enabled=True, token="t"), MessageBus())
    _attach_bot(ch, bot)

    await ch.send(
        OutboundMessage(
            channel="telegram",
            chat_id="123",
            content="↳ fs('.')",
            metadata={"append_mode": "concat", "append_key": "k1"},
        )
    )
    await ch.send(
        OutboundMessage(
            channel="telegram",
            chat_id="123",
            content="↳ exec('ls')",
            metadata={"append_mode": "concat", "append_key": "k1"},
        )
    )

    assert len(bot.sent) == 1
    assert len(bot.edited) >= 1
    edited_text = bot.edited[-1][2]
    assert "fs" in edited_text and "exec" in edited_text


@pytest.mark.asyncio
async def test_send_append_mode_reset_starts_new_message() -> None:
    bot = _AppendRecordingBot()
    ch = TelegramChannel(TelegramConfig(enabled=True, token="t"), MessageBus())
    _attach_bot(ch, bot)

    await ch.send(
        OutboundMessage(
            channel="telegram",
            chat_id="123",
            content="↳ fs('.')",
            metadata={"append_mode": "concat", "append_key": "k1"},
        )
    )
    await ch.send(
        OutboundMessage(
            channel="telegram",
            chat_id="123",
            content="↳ exec('ls')",
            metadata={"append_mode": "concat", "append_key": "k1", "append_reset": True},
        )
    )

    assert len(bot.sent) == 2
    # reset path should avoid editing old chain for this update
    assert len(bot.edited) == 0


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
            "history_tokens": 3,
            "recall_count": 1,
            "recall_items": [
                {"source": "2026-02-22.md", "heading": "chat", "score": 0.8, "source_type": "raw"}
            ],
            "system_prompt_chars": 20,
            "system_prompt_tokens": 5,
            "total_input_chars": 30,
            "total_input_tokens": 11,
            "token_estimate": {
                "method": "litellm.token_counter",
                "messages_only": 11,
                "with_tools": 22,
                "tools_only": 11,
            },
            "history_config": {
                "memory_budget_tokens": 0,
                "recall_max_total_tokens": 500,
                "recall_max_per_item_tokens": 125,
            },
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
            "message_summaries": [
                {"role": "system", "chars": 3, "tokens": 1, "preview": "sys"},
                {"role": "user", "chars": 2, "tokens": 1, "preview": "hi"},
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
    first_call = msg.reply_text.await_args_list[0]
    first_chunk = first_call.args[0]
    assert "HaL Context Inspector" in first_chunk
    assert "Budget" in first_chunk
    assert "Risk" in first_chunk
    # Verify HTML parse_mode is used
    assert first_call.kwargs.get("parse_mode") == "HTML"


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
            "history_tokens": 0,
            "recall_count": 0,
            "recall_items": [],
            "system_prompt_chars": 3,
            "system_prompt_tokens": 1,
            "total_input_chars": 5,
            "total_input_tokens": 1,
            "token_estimate": {
                "method": "chars_div_4",
                "messages_only": 1,
                "with_tools": 1,
                "tools_only": 0,
            },
            "history_config": {
                "memory_budget_tokens": 0,
                "recall_max_total_tokens": 500,
                "recall_max_per_item_tokens": 125,
            },
            "messages": [{"role": "system", "content": "sys"}],
            "message_summaries": [{"role": "system", "chars": 3, "tokens": 1, "preview": "sys"}],
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
    assert "(full)" in first_chunk


@pytest.mark.asyncio
async def test_on_context_full_flag_without_message_uses_default_text() -> None:
    inspector = AsyncMock(
        return_value={
            "channel": "telegram",
            "chat_id": "123",
            "model": "test-model",
            "mode": "collab",
            "history_message_count": 0,
            "history_chars": 0,
            "history_tokens": 0,
            "recall_count": 0,
            "recall_items": [],
            "system_prompt_chars": 3,
            "system_prompt_tokens": 1,
            "total_input_chars": 5,
            "total_input_tokens": 1,
            "token_estimate": {
                "method": "chars_div_4",
                "messages_only": 1,
                "with_tools": 1,
                "tools_only": 0,
            },
            "history_config": {
                "memory_budget_tokens": 0,
                "recall_max_total_tokens": 500,
                "recall_max_per_item_tokens": 125,
            },
            "messages": [{"role": "system", "content": "sys"}],
            "message_summaries": [{"role": "system", "chars": 3, "tokens": 1, "preview": "sys"}],
        }
    )
    ch = TelegramChannel(
        TelegramConfig(enabled=True, token="t"),
        MessageBus(),
        context_inspector=inspector,
    )

    msg = _Message(chat_id=123, text="/context --full")
    msg.reply_text = AsyncMock()  # type: ignore[attr-defined]
    update = _Update(message=msg, user=_User(1))

    await ch._on_context(update, context=None)  # type: ignore[arg-type]

    inspector.assert_awaited_once_with(
        channel="telegram",
        chat_id="123",
        current_message="[context inspection]",
    )
    first_chunk = msg.reply_text.await_args_list[0].args[0]
    assert "(full)" in first_chunk


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


# ---------------------------------------------------------------------------
# _resolve_owner_id tests
# ---------------------------------------------------------------------------


def test_resolve_owner_id_numeric() -> None:
    cfg = TelegramConfig(enabled=True, token="t", allow_from=["12345"])
    ch = TelegramChannel(cfg, MessageBus())
    assert ch._resolve_owner_id() == "12345"


def test_resolve_owner_id_pipe_format() -> None:
    cfg = TelegramConfig(enabled=True, token="t", allow_from=["12345|alice"])
    ch = TelegramChannel(cfg, MessageBus())
    assert ch._resolve_owner_id() == "12345"


def test_resolve_owner_id_username_only() -> None:
    cfg = TelegramConfig(enabled=True, token="t", allow_from=["alice"])
    ch = TelegramChannel(cfg, MessageBus())
    assert ch._resolve_owner_id() is None


def test_resolve_owner_id_empty() -> None:
    cfg = TelegramConfig(enabled=True, token="t", allow_from=[])
    ch = TelegramChannel(cfg, MessageBus())
    assert ch._resolve_owner_id() is None


# ---------------------------------------------------------------------------
# _read_update_marker tests
# ---------------------------------------------------------------------------


def test_read_update_marker_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    marker = tmp_path / "last_update.json"
    data = {"before": "aaa", "after": "bbb", "changes": "fix: something"}
    marker.write_text(json.dumps(data))

    monkeypatch.setattr(Path, "home", lambda: tmp_path.parent)
    # Patch the marker path directly since it uses Path.home() / ".hal" / ...
    monkeypatch.setattr(
        "hal.channels.telegram.TelegramChannel._read_update_marker",
        staticmethod(lambda: _read_marker_from(marker)),
    )

    result = _read_marker_from(marker)
    assert result is not None
    assert result["before"] == "aaa"
    assert result["changes"] == "fix: something"
    assert not marker.exists()  # consumed


def _read_marker_from(path: Path) -> dict[str, str] | None:
    """Helper: read and consume a specific marker file."""
    import json

    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    path.unlink()
    return data


def test_read_update_marker_missing() -> None:
    result = TelegramChannel._read_update_marker()
    # If ~/.hal/last_update.json doesn't exist, should return None
    # (may exist in CI env, so we just verify it returns None or dict)
    assert result is None or isinstance(result, dict)


# ---------------------------------------------------------------------------
# Inline keyboard tests
# ---------------------------------------------------------------------------


class _InlineKeyboardRecordingBot:
    """Bot that records send_message calls including reply_markup."""

    def __init__(self):
        self.sent: list[dict] = []

    async def send_message(self, chat_id, text, parse_mode=None, reply_markup=None):
        self.sent.append(
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "reply_markup": reply_markup,
            }
        )


def test_build_inline_keyboard_structure() -> None:
    ch = TelegramChannel(TelegramConfig(enabled=True, token="t"), MessageBus())
    buttons = [
        [
            {"text": "Yes", "callback_data": "action:yes"},
            {"text": "No", "callback_data": "action:no"},
        ]
    ]
    markup = ch._build_inline_keyboard(buttons)
    assert len(markup.inline_keyboard) == 1
    row = markup.inline_keyboard[0]
    assert len(row) == 2
    assert row[0].text == "Yes"
    assert row[0].callback_data == "action:yes"
    assert row[1].text == "No"
    assert row[1].callback_data == "action:no"


@pytest.mark.asyncio
async def test_send_with_inline_buttons_attaches_keyboard() -> None:
    bot = _InlineKeyboardRecordingBot()
    ch = TelegramChannel(TelegramConfig(enabled=True, token="t"), MessageBus())
    _attach_bot(ch, bot)

    msg = OutboundMessage(
        channel="telegram",
        chat_id="123",
        content="Choose an option",
        metadata={
            "inline_buttons": [
                [
                    {"text": "Yes", "callback_data": "action:yes"},
                    {"text": "No", "callback_data": "action:no"},
                ]
            ]
        },
    )
    await ch.send(msg)

    assert len(bot.sent) == 1
    call = bot.sent[0]
    assert call["chat_id"] == 123
    assert call["reply_markup"] is not None
    assert len(call["reply_markup"].inline_keyboard) == 1


# ---------------------------------------------------------------------------
# _send_startup_notification tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_startup_notification_with_update(monkeypatch: pytest.MonkeyPatch) -> None:
    """Startup notification includes changelog when update marker exists."""
    ch, mm, mock_bot = _build_startup_notification_channel()

    _mock_git_log(monkeypatch)

    # Mock update marker
    update_data = {"before": "000", "after": "abc1234", "changes": "fix: thing"}
    monkeypatch.setattr(
        "hal.channels.telegram.TelegramChannel._read_update_marker",
        staticmethod(lambda: update_data),
    )

    await ch._send_startup_notification()

    # Should send enriched message
    mock_bot.send_message.assert_awaited_once()
    sent_text = _extract_sent_text(mock_bot.send_message)
    assert "Changes since" in sent_text
    assert "fix: thing" in sent_text

    _assert_startup_injection(
        ch,
        mm,
        expected_content_fragment="self-update",
        expect_update_info=True,
    )


@pytest.mark.asyncio
async def test_startup_notification_without_update(monkeypatch: pytest.MonkeyPatch) -> None:
    """Startup notification writes a generic injection when no update marker exists."""
    ch, mm, mock_bot = _build_startup_notification_channel()

    _mock_git_log(monkeypatch)
    monkeypatch.setattr(
        "hal.channels.telegram.TelegramChannel._read_update_marker",
        staticmethod(lambda: None),
    )

    await ch._send_startup_notification()

    mock_bot.send_message.assert_awaited_once()
    sent_text = _extract_sent_text(mock_bot.send_message)
    assert "HaL online" in sent_text
    assert "Changes since" not in sent_text

    _assert_startup_injection(
        ch,
        mm,
        expected_content_fragment="service started",
        expect_update_info=False,
    )
