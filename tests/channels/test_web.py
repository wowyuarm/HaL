from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from hal.bus.events import OutboundMessage
from hal.bus.queue import MessageBus
from hal.channels.commands import build_slash_command_text, parse_context_command
from hal.channels.web import WebChannel
from hal.channels.web.protocol import build_history, serialize_outbound
from hal.infra.config.schema import WebConfig
from hal.workspace.layout import WorkspaceLayout
from hal.workspace.sessions import SessionRepository


def _build_channel(
    tmp_path: Path, *, context_inspector: AsyncMock | None = None
) -> WebChannel:
    return WebChannel(
        WebConfig(enabled=True),
        MessageBus(),
        workspace_layout=WorkspaceLayout(tmp_path),
        context_inspector=context_inspector,
    )


def test_serialize_outbound_generates_fallback_message_id() -> None:
    envelope = serialize_outbound(OutboundMessage(channel="web", chat_id="web", content="hello"))

    assert envelope["type"] == "message"
    assert envelope["id"].startswith("msg_")
    assert envelope["content"] == "hello"


def test_shared_command_helpers_cover_context_and_brief_cases() -> None:
    assert parse_context_command("/context") == "[context inspection]"
    assert parse_context_command("/context auth.py") == "auth.py"
    assert build_slash_command_text("brief", {"raw": "focus on architecture"}) == (
        "/brief focus on architecture"
    )


def test_build_history_filters_internal_messages_and_normalizes_tool_calls() -> None:
    history = build_history(
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello", "id": "u1", "ts": "2026-03-11T12:00:00Z"},
            {
                "role": "assistant",
                "content": "done",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "exec", "arguments": '{"cmd":"ruff check"}'},
                    }
                ],
            },
            {"role": "tool", "content": "ignored"},
        ]
    )

    assert [item["role"] for item in history] == ["user", "assistant"]
    assert history[0]["id"] == "u1"
    assert history[1]["metadata"]["tool_calls"][0]["name"] == "exec"
    assert "ruff check" in history[1]["metadata"]["tool_calls"][0]["args_summary"]


@pytest.mark.asyncio
async def test_web_channel_dispatch_command_preserves_brief_arguments(tmp_path: Path) -> None:
    channel = _build_channel(tmp_path)
    channel._handle_message = AsyncMock()  # type: ignore[method-assign]
    channel._push_status = AsyncMock()  # type: ignore[method-assign]

    await channel._dispatch_command(  # type: ignore[attr-defined]
        {"name": "brief", "args": {"raw": "please summarize auth decisions"}},
        AsyncMock(),
    )

    channel._push_status.assert_awaited_once_with("processing")  # type: ignore[attr-defined]
    channel._handle_message.assert_awaited_once()  # type: ignore[attr-defined]
    assert channel._handle_message.await_args.kwargs["content"] == (  # type: ignore[attr-defined]
        "/brief please summarize auth decisions"
    )


@pytest.mark.asyncio
async def test_web_channel_snapshot_uses_persisted_session_history(tmp_path: Path) -> None:
    repository = SessionRepository(tmp_path)
    repository.write_snapshot(
        session_key="web:web",
        channel="web",
        chat_id="web",
        messages=[
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ],
    )
    channel = _build_channel(tmp_path)

    history = channel._build_history()  # type: ignore[attr-defined]

    assert [item["role"] for item in history] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_web_channel_context_summary_uses_inspector_payload(tmp_path: Path) -> None:
    inspector = AsyncMock(
        return_value={
            "total_input_tokens": 321,
            "tools_count": 14,
            "history_message_count": 8,
        }
    )
    channel = _build_channel(tmp_path, context_inspector=inspector)

    summary = await channel._build_context_summary_payload()  # type: ignore[attr-defined]

    assert summary == {"tokens": 321, "tools": 14, "history": 8}


@pytest.mark.asyncio
async def test_web_channel_replaces_existing_socket_with_valid_close_code(tmp_path: Path) -> None:
    channel = _build_channel(tmp_path)
    old_ws = AsyncMock()
    old_ws.closed = False
    new_ws = AsyncMock()
    channel._ws = old_ws  # type: ignore[attr-defined]
    channel._push_snapshot = AsyncMock()  # type: ignore[method-assign]

    await channel._on_ws_connect(new_ws)  # type: ignore[attr-defined]

    old_ws.close.assert_awaited_once()
    assert old_ws.close.await_args.kwargs["code"] == 1001
