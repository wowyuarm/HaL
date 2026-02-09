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


@pytest.mark.asyncio
async def test_spawn_runs_task_and_announces_result(tmp_path) -> None:
    bus = MessageBus()

    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test-model"

    # First call: tool call to list workspace. Second call: final response.
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

    mgr = SubagentManager(provider=provider, workspace=tmp_path, bus=bus, restrict_to_workspace=True)

    msg = await mgr.spawn(task="list files", label="L", origin_channel="cli", origin_chat_id="direct")
    assert "started" in msg
    assert "id:" in msg

    inbound = await asyncio.wait_for(bus.consume_inbound(), timeout=2.0)
    assert isinstance(inbound, InboundMessage)
    assert inbound.channel == "system"
    assert inbound.sender_id == "subagent"
    assert "Result:" in inbound.content
    assert "done" in inbound.content

    # Task should be cleaned up (done callback may run slightly after message publish)
    await _wait_running_count(mgr, 0)


def test_build_subagent_prompt_includes_workspace_and_task(tmp_path) -> None:
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    mgr = SubagentManager(provider=provider, workspace=tmp_path, bus=MessageBus())

    prompt = mgr._build_subagent_prompt("do thing")
    assert "do thing" in prompt
    assert str(tmp_path) in prompt


@pytest.mark.asyncio
async def test_subagent_error_path_announces_error(tmp_path) -> None:
    bus = MessageBus()

    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test-model"
    provider.chat = AsyncMock(side_effect=RuntimeError("boom"))

    mgr = SubagentManager(provider=provider, workspace=tmp_path, bus=bus)

    await mgr.spawn(task="x", origin_channel="cli", origin_chat_id="direct")

    inbound = await asyncio.wait_for(bus.consume_inbound(), timeout=2.0)
    assert "Error: boom" in inbound.content

    await _wait_running_count(mgr, 0)
