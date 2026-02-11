from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from hal.bus.events import InboundMessage
from hal.bus.queue import MessageBus
from hal.core.subagent import SubagentManager
from hal.infra.providers.base import LLMProvider, LLMResponse, ToolCallRequest


async def _wait_running_count(mgr: SubagentManager, expected: int, timeout: float = 2.0) -> None:
    """Wait for SubagentManager.get_running_count() to reach expected."""
    start = asyncio.get_running_loop().time()
    while asyncio.get_running_loop().time() - start < timeout:
        if mgr.get_running_count() == expected:
            return
        await asyncio.sleep(0)
    assert mgr.get_running_count() == expected


# ------------------------------------------------------------------
# Synchronous run() — default path
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_returns_result_directly(tmp_path) -> None:
    """run() awaits the subagent and returns its result as a string."""
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test-model"
    provider.chat = AsyncMock(
        return_value=LLMResponse(content="found 3 files", tool_calls=[], finish_reason="stop"),
    )

    mgr = SubagentManager(provider=provider, workspace=tmp_path, bus=MessageBus())
    result = await mgr.run(task="list files", label="L")

    assert result == "found 3 files"
    assert provider.chat.await_count == 1


@pytest.mark.asyncio
async def test_run_executes_tool_calls(tmp_path) -> None:
    """run() drives the subagent loop through tool calls until a final response."""
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test-model"
    provider.chat = AsyncMock(
        side_effect=[
            LLMResponse(
                content="calling tool",
                tool_calls=[
                    ToolCallRequest(
                        id="1",
                        name="fs",
                        arguments={"action": "list", "path": str(tmp_path)},
                    )
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="done listing", tool_calls=[], finish_reason="stop"),
        ]
    )

    mgr = SubagentManager(
        provider=provider, workspace=tmp_path, bus=MessageBus(), restrict_to_workspace=True
    )
    result = await mgr.run(task="list files")

    assert result == "done listing"
    assert provider.chat.await_count == 2


@pytest.mark.asyncio
async def test_run_error_propagates(tmp_path) -> None:
    """run() lets exceptions propagate to the caller."""
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test-model"
    provider.chat = AsyncMock(side_effect=RuntimeError("boom"))

    mgr = SubagentManager(provider=provider, workspace=tmp_path, bus=MessageBus())

    with pytest.raises(RuntimeError, match="boom"):
        await mgr.run(task="x")


# ------------------------------------------------------------------
# Background spawn_background() — fire-and-forget path
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spawn_background_announces_result(tmp_path) -> None:
    """spawn_background() runs in background and announces via bus."""
    bus = MessageBus()

    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test-model"
    provider.chat = AsyncMock(
        side_effect=[
            LLMResponse(
                content="calling tool",
                tool_calls=[
                    ToolCallRequest(
                        id="1",
                        name="fs",
                        arguments={"action": "list", "path": str(tmp_path)},
                    )
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="done", tool_calls=[], finish_reason="stop"),
        ]
    )

    mgr = SubagentManager(
        provider=provider, workspace=tmp_path, bus=bus, restrict_to_workspace=True
    )

    msg = await mgr.spawn_background(
        task="list files", label="L", origin_channel="cli", origin_chat_id="direct"
    )
    assert "started" in msg
    assert "id:" in msg

    inbound = await asyncio.wait_for(bus.consume_inbound(), timeout=2.0)
    assert isinstance(inbound, InboundMessage)
    assert inbound.channel == "system"
    assert inbound.sender_id == "subagent"
    assert "Result:" in inbound.content
    assert "done" in inbound.content

    await _wait_running_count(mgr, 0)


@pytest.mark.asyncio
async def test_spawn_background_error_announces_error(tmp_path) -> None:
    """spawn_background() catches errors and announces them via bus."""
    bus = MessageBus()

    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test-model"
    provider.chat = AsyncMock(side_effect=RuntimeError("boom"))

    mgr = SubagentManager(provider=provider, workspace=tmp_path, bus=bus)

    await mgr.spawn_background(task="x", origin_channel="cli", origin_chat_id="direct")

    inbound = await asyncio.wait_for(bus.consume_inbound(), timeout=2.0)
    assert "Error: boom" in inbound.content

    await _wait_running_count(mgr, 0)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def test_build_subagent_prompt_includes_workspace_and_task(tmp_path) -> None:
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    mgr = SubagentManager(provider=provider, workspace=tmp_path, bus=MessageBus())

    prompt = mgr._build_subagent_prompt("do thing")
    assert "do thing" in prompt
    assert str(tmp_path) in prompt


def test_build_subagent_prompt_includes_mode_directive(tmp_path) -> None:
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    mgr = SubagentManager(provider=provider, workspace=tmp_path, bus=MessageBus())

    prompt = mgr._build_subagent_prompt("do thing")
    assert "Focused Task" in prompt
