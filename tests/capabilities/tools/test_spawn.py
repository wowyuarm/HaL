from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from hal.capabilities.tools.spawn import SpawnTool
from hal.core.ports import SubagentExecutionResult


def test_format_result_includes_structured_subagent_metadata() -> None:
    details = SubagentExecutionResult(
        content="done",
        artifact_path=Path("/tmp/report.md"),
        total_tokens=42,
        record_id="abc123",
        status="partial",
        has_side_effects=True,
        tools_used=["fs", "web_search"],
        tool_call_counts={"fs": 2, "web_search": 1},
        files_modified=["/tmp/report.md"],
        commands_run=["ls -la"],
        tool_errors=["web_search: Error: Invalid parameters"],
        missing_artifacts=[Path("/tmp/missing.md")],
        log_path=Path("/tmp/subagent-log.jsonl"),
    )

    text = SpawnTool._format_result(details)

    assert "[Subagent Record ID] abc123" in text
    assert "[Subagent Status] partial" in text
    assert "[Subagent Artifact] /tmp/report.md" in text
    assert "[Subagent Log] /tmp/subagent-log.jsonl" in text
    assert "[Subagent Total Tokens] 42" in text
    assert '[Subagent Tools Used] ["fs", "web_search"]' in text
    assert '[Subagent Tool Counts] {"fs": 2, "web_search": 1}' in text
    assert "[Subagent Has Side Effects] true" in text
    assert '[Subagent Files Modified] ["/tmp/report.md"]' in text
    assert '[Subagent Commands Run] ["ls -la"]' in text
    assert '[Subagent Tool Errors] ["web_search: Error: Invalid parameters"]' in text
    assert '[Subagent Missing Artifacts] ["/tmp/missing.md"]' in text


class _ManagerStub:
    def __init__(self) -> None:
        self.spawn_background = AsyncMock(return_value="started")
        self.run_with_details = AsyncMock()
        self.get_running_count = lambda: 0
        self.get_last_iteration = lambda: 0


@pytest.mark.asyncio
async def test_background_spawn_does_not_start_progress_reporting() -> None:
    manager = _ManagerStub()
    send_callback = AsyncMock()
    tool = SpawnTool(manager=manager, send_callback=send_callback)
    tool.set_context("telegram", "42")

    out = await tool.execute(task="do work", label="L", background=True)

    assert out == "started"
    manager.spawn_background.assert_awaited_once()
    send_callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_background_spawn_passes_session_context() -> None:
    manager = _ManagerStub()
    tool = SpawnTool(manager=manager)
    tool.set_context("telegram", "42")

    await tool.execute(task="do work", label="L", background=True)

    kwargs = manager.spawn_background.await_args.kwargs
    assert kwargs["channel"] == "telegram"
    assert kwargs["chat_id"] == "42"
    assert kwargs["session_key"] == "telegram:42"
