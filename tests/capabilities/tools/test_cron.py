from __future__ import annotations

from pathlib import Path

import pytest

from hal.capabilities.scheduling.cron_service import CronService
from hal.capabilities.tools.schedule import CronTool


@pytest.mark.asyncio
async def test_cron_tool_unknown_action(tmp_path: Path) -> None:
    tool = CronTool(CronService(tmp_path / "jobs.json"))
    out = await tool.execute(action="noop")
    assert "Unknown action" in out


@pytest.mark.asyncio
async def test_cron_tool_add_requires_message_and_context(tmp_path: Path) -> None:
    tool = CronTool(CronService(tmp_path / "jobs.json"))

    out = await tool.execute(action="add", message="", every_seconds=1)
    assert "message" in out.lower()

    out2 = await tool.execute(action="add", message="hi", every_seconds=1)
    assert "no session context" in out2.lower()


@pytest.mark.asyncio
async def test_cron_tool_add_requires_schedule(tmp_path: Path) -> None:
    tool = CronTool(CronService(tmp_path / "jobs.json"))
    tool.set_context("telegram", "123")

    out = await tool.execute(action="add", message="hi")
    assert "either" in out.lower()


@pytest.mark.asyncio
async def test_cron_tool_add_list_remove(tmp_path: Path) -> None:
    service = CronService(tmp_path / "jobs.json")
    tool = CronTool(service)
    tool.set_context("telegram", "123")

    created = await tool.execute(action="add", message="hello world", every_seconds=60)
    assert "Created job" in created

    listing = await tool.execute(action="list")
    assert "Scheduled jobs" in listing
    assert "hello world" in listing

    job_id = service.list_jobs(include_disabled=True)[0].id

    removed = await tool.execute(action="remove", job_id=job_id)
    assert "Removed job" in removed

    missing = await tool.execute(action="remove", job_id=job_id)
    assert "not found" in missing.lower()


@pytest.mark.asyncio
async def test_cron_tool_add_persists_tools_whitelist(tmp_path: Path) -> None:
    service = CronService(tmp_path / "jobs.json")
    tool = CronTool(service)
    tool.set_context("telegram", "123")

    created = await tool.execute(
        action="add",
        message="hello world",
        every_seconds=60,
        tools=["fs", "web_search"],
    )
    assert "Created job" in created

    job = service.list_jobs(include_disabled=True)[0]
    assert job.payload.tools == ["fs", "web_search"]


@pytest.mark.asyncio
async def test_cron_tool_list_empty(tmp_path: Path) -> None:
    tool = CronTool(CronService(tmp_path / "jobs.json"))
    tool.set_context("cli", "direct")

    out = await tool.execute(action="list")
    assert "No scheduled jobs" in out


@pytest.mark.asyncio
async def test_cron_tool_remove_requires_job_id(tmp_path: Path) -> None:
    tool = CronTool(CronService(tmp_path / "jobs.json"))
    out = await tool.execute(action="remove", job_id=None)
    assert "job_id" in out
