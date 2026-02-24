from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from hal.core.subagent import SubagentExecutionResult, SubagentManager
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
async def test_run_with_details_appends_jsonl_log(tmp_path: Path) -> None:
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test-model"
    provider.chat = AsyncMock(
        return_value=LLMResponse(
            content="found 3 files",
            tool_calls=[],
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            finish_reason="stop",
        ),
    )

    mgr = SubagentManager(provider=provider, workspace=tmp_path)
    details = await mgr.run_with_details(task="list files", label="L")

    assert isinstance(details, SubagentExecutionResult)
    assert details.content == "found 3 files"
    assert details.total_tokens == 15
    assert details.record_id
    assert details.log_path is not None
    assert details.log_path.exists()
    assert details.artifact_path is not None
    assert details.artifact_path == details.log_path

    records = [
        json.loads(line)
        for line in details.log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(records) == 1
    assert records[0]["id"] == details.record_id
    assert records[0]["task"] == "list files"
    assert records[0]["result"] == "found 3 files"
    assert records[0]["status"] == "completed"
    assert records[0]["artifacts"] == []
    assert sorted(p.name for p in details.log_path.parent.iterdir()) == ["subagent-log.jsonl"]


@pytest.mark.asyncio
async def test_run_with_details_keeps_full_task_and_result_in_log(tmp_path: Path) -> None:
    long_task = "task-" + "x" * 500
    long_result = "result-" + "y" * 1200

    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test-model"
    provider.chat = AsyncMock(
        return_value=LLMResponse(
            content=long_result,
            tool_calls=[],
            usage={"total_tokens": 42},
            finish_reason="stop",
        ),
    )

    mgr = SubagentManager(provider=provider, workspace=tmp_path)
    details = await mgr.run_with_details(task=long_task, label="long")

    assert details.log_path is not None
    record = json.loads(details.log_path.read_text(encoding="utf-8").strip())
    assert record["task"] == long_task
    assert record["result"] == long_result


@pytest.mark.asyncio
async def test_run_with_details_extracts_report_artifact_paths(tmp_path: Path) -> None:
    report = tmp_path / "artifacts" / "subagent" / "report.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("# report", encoding="utf-8")

    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test-model"
    provider.chat = AsyncMock(
        return_value=LLMResponse(
            content=f"Done. Full report: `{report}`",
            tool_calls=[],
            finish_reason="stop",
        ),
    )

    mgr = SubagentManager(provider=provider, workspace=tmp_path)
    details = await mgr.run_with_details(task="report task", label="R")

    assert details.log_path is not None
    assert details.artifacts == [report]
    assert details.artifact_path == report
    record = json.loads(details.log_path.read_text(encoding="utf-8").strip())
    assert record["artifacts"] == [str(report)]


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
        assert result.content == "done"
        assert result.record_id
        assert result.log_path is not None
        assert result.log_path.exists()
        assert result.artifact_path is not None

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
    assert "Error:" in result.content
    assert "boom" in result.content
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


def test_max_iterations_from_config(tmp_path) -> None:
    """max_iterations should use the value passed at construction, not a hardcoded default."""
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test-model"

    # Default should match config schema default (20)
    mgr_default = SubagentManager(provider=provider, workspace=tmp_path)
    assert mgr_default.max_iterations == 20

    # Custom value should be respected
    mgr_custom = SubagentManager(provider=provider, workspace=tmp_path, max_iterations=35)
    assert mgr_custom.max_iterations == 35


def test_build_system_prompt_includes_workspace(tmp_path) -> None:
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    mgr = SubagentManager(provider=provider, workspace=tmp_path)

    prompt = mgr._build_system_prompt()
    assert str(tmp_path) in prompt


def test_build_system_prompt_does_not_include_task(tmp_path) -> None:
    """System prompt should be task-agnostic; task is in user message only."""
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    mgr = SubagentManager(provider=provider, workspace=tmp_path)

    prompt = mgr._build_system_prompt()
    assert "Your Task" not in prompt


def test_build_system_prompt_includes_mode_directive(tmp_path) -> None:
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    mgr = SubagentManager(provider=provider, workspace=tmp_path)

    prompt = mgr._build_system_prompt()
    assert "Focused Task" in prompt


def test_build_system_prompt_includes_tool_guide(tmp_path) -> None:
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    mgr = SubagentManager(provider=provider, workspace=tmp_path)

    prompt = mgr._build_system_prompt()
    assert "fs(action=" in prompt
    assert "exec(command=" in prompt
    assert "web_search(query=" in prompt
    assert "web_fetch(url=" in prompt


def test_build_system_prompt_includes_time(tmp_path) -> None:
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    mgr = SubagentManager(provider=provider, workspace=tmp_path)

    prompt = mgr._build_system_prompt()
    assert "Current time:" in prompt


def test_build_skills_section_uses_workspace_skill_script_path(tmp_path) -> None:
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    mgr = SubagentManager(provider=provider, workspace=tmp_path)

    skill_dir = tmp_path / "skills" / "deepwiki"
    script_path = skill_dir / "scripts" / "deepwiki.sh"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("#!/bin/sh\n", encoding="utf-8")
    (skill_dir / "SKILL.md").write_text(
        """---
name: deepwiki
description: DeepWiki helper
---
Run `scripts/deepwiki.sh` to inspect repository docs.
""",
        encoding="utf-8",
    )

    section = mgr._build_skills_section()

    assert section is not None
    assert str(script_path) in section
    assert "`scripts/deepwiki.sh`" not in section
