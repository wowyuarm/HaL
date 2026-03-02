from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from hal.capabilities.scheduling.runner import CronAgentRunner
from hal.capabilities.scheduling.types import CronJob, CronPayload, CronSchedule
from hal.core.runtime.loop import LoopMetadata
from hal.core.runtime.summary import generate_cron_summary
from hal.infra.providers.base import LLMProvider, LLMResponse, ToolCallRequest


def _job(job_id: str = "job1") -> CronJob:
    return CronJob(
        id=job_id,
        name="daily-check",
        schedule=CronSchedule(kind="every", every_ms=60_000),
        payload=CronPayload(message="check updates", deliver=False),
    )


@pytest.mark.asyncio
async def test_cron_runner_with_context_executes_isolated_loop(tmp_path: Path) -> None:
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test-model"
    provider.chat = AsyncMock(
        side_effect=[
            LLMResponse(
                content="listing",
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

    cron_dir = tmp_path / "cron"
    (cron_dir / "job1").mkdir(parents=True, exist_ok=True)
    (cron_dir / "job1" / "context.md").write_text("Check for updates daily.", encoding="utf-8")

    runner = CronAgentRunner(
        cron_dir=cron_dir,
        provider=provider,
        model="test-model",
        workspace=tmp_path,
        restrict_to_workspace=True,
        max_iterations=5,
    )

    result = await runner.run(_job("job1"), "Check updates now")

    assert result is not None
    content, meta = result
    assert content == "done"
    assert meta.tools_used == ["fs"]

    entries = runner.get_log("job1").get_recent_entries(10)
    assert entries[0].role == "user"
    assert entries[-1].role == "assistant"
    assert any(e.role == "tool" and e.tool_name == "fs" for e in entries)


@pytest.mark.asyncio
async def test_cron_runner_without_context_returns_none(tmp_path: Path) -> None:
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test-model"
    provider.chat = AsyncMock(return_value=LLMResponse(content="done", tool_calls=[]))

    runner = CronAgentRunner(
        cron_dir=tmp_path / "cron",
        provider=provider,
        model="test-model",
        workspace=tmp_path,
    )

    result = await runner.run(_job("job1"), "Check updates now")

    assert result is None
    provider.chat.assert_not_awaited()


def test_cron_runner_toolset_is_restricted(tmp_path: Path) -> None:
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test-model"

    runner = CronAgentRunner(
        cron_dir=tmp_path / "cron",
        provider=provider,
        model="test-model",
        workspace=tmp_path,
    )

    tools = runner._build_tools(_job("job1"))

    assert set(tools.tool_names) == {"fs", "exec", "web_search", "web_fetch"}
    assert "spawn" not in tools.tool_names
    assert "cron" not in tools.tool_names
    assert "message" not in tools.tool_names
    assert "recall" not in tools.tool_names


@pytest.mark.asyncio
async def test_generate_cron_summary_writes_to_per_job_log(tmp_path: Path) -> None:
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test-model"
    provider.chat = AsyncMock(
        return_value=LLMResponse(
            content="**Outcome**: done\n**Files modified**: none\n**Commands run**: none"
            "\n**Open issues**: none\n**Failed actions**: none",
            tool_calls=[],
            finish_reason="stop",
        )
    )

    runner = CronAgentRunner(
        cron_dir=tmp_path / "cron",
        provider=provider,
        model="test-model",
        workspace=tmp_path,
    )

    await generate_cron_summary(
        meta=LoopMetadata(iterations=5),
        final_content="done",
        cron_log=runner.get_log("job1"),
        provider=provider,
        model="test-model",
        job_id="job1",
    )

    summaries = runner.get_log("job1").get_recent_summaries(1)
    assert len(summaries) == 1
    assert summaries[0].entry_type == "summary"
    assert "[System Summary]" in summaries[0].content
