from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from hal.core.subagent import SubagentManager
from hal.infra.providers.base import LLMProvider, LLMResponse, ToolCallRequest

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

    mgr = SubagentManager(provider=provider, workspace=tmp_path)
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

    mgr = SubagentManager(provider=provider, workspace=tmp_path, restrict_to_workspace=True)
    result = await mgr.run(task="list files")

    assert result == "done listing"
    assert provider.chat.await_count == 2


@pytest.mark.asyncio
async def test_run_error_propagates(tmp_path) -> None:
    """run() lets exceptions propagate to the caller."""
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test-model"
    provider.chat = AsyncMock(side_effect=RuntimeError("boom"))

    mgr = SubagentManager(provider=provider, workspace=tmp_path)

    with pytest.raises(RuntimeError, match="boom"):
        await mgr.run(task="x")


# ------------------------------------------------------------------
# Background spawn_background() — parallel execution path
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spawn_background_returns_started_message(tmp_path) -> None:
    """spawn_background() returns a status message and tracks the task."""
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test-model"
    provider.chat = AsyncMock(
        return_value=LLMResponse(content="done", tool_calls=[], finish_reason="stop"),
    )

    mgr = SubagentManager(provider=provider, workspace=tmp_path)
    msg = await mgr.spawn_background(task="list files", label="L")

    assert "started" in msg
    assert "id:" in msg
    assert mgr.get_running_count() == 1

    # Clean up
    await mgr.await_pending()


@pytest.mark.asyncio
async def test_await_pending_collects_results(tmp_path) -> None:
    """await_pending() waits for all background tasks and returns results."""
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test-model"
    provider.chat = AsyncMock(
        return_value=LLMResponse(content="done", tool_calls=[], finish_reason="stop"),
    )

    mgr = SubagentManager(provider=provider, workspace=tmp_path)
    await mgr.spawn_background(task="task1", label="T1")
    await mgr.spawn_background(task="task2", label="T2")

    results = await mgr.await_pending()
    assert len(results) == 2
    labels = {label for label, _ in results}
    assert labels == {"T1", "T2"}
    for _, result in results:
        assert result == "done"

    assert mgr.get_running_count() == 0


@pytest.mark.asyncio
async def test_await_pending_handles_errors(tmp_path) -> None:
    """await_pending() catches errors and returns them as error strings."""
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test-model"
    provider.chat = AsyncMock(side_effect=RuntimeError("boom"))

    mgr = SubagentManager(provider=provider, workspace=tmp_path)
    await mgr.spawn_background(task="x")

    results = await mgr.await_pending()
    assert len(results) == 1
    label, result = results[0]
    assert "Error:" in result
    assert "boom" in result
    assert mgr.get_running_count() == 0


@pytest.mark.asyncio
async def test_await_pending_empty_returns_empty_list(tmp_path) -> None:
    """await_pending() returns [] when no tasks are pending."""
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test-model"

    mgr = SubagentManager(provider=provider, workspace=tmp_path)
    results = await mgr.await_pending()
    assert results == []


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def test_build_subagent_prompt_includes_workspace_and_task(tmp_path) -> None:
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    mgr = SubagentManager(provider=provider, workspace=tmp_path)

    prompt = mgr._build_subagent_prompt("do thing")
    assert "do thing" in prompt
    assert str(tmp_path) in prompt


def test_build_subagent_prompt_includes_mode_directive(tmp_path) -> None:
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    mgr = SubagentManager(provider=provider, workspace=tmp_path)

    prompt = mgr._build_subagent_prompt("do thing")
    assert "Focused Task" in prompt
