from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from hal.capabilities.scheduling.cron_service import CronService, _compute_next_run, _now_ms
from hal.capabilities.scheduling.heartbeat import (
    HEARTBEAT_OK_TOKEN,
    HEARTBEAT_PROMPT,
    HeartbeatService,
    _is_heartbeat_empty,
)
from hal.capabilities.scheduling.types import CronSchedule


def test_compute_next_run_at_and_every(monkeypatch: pytest.MonkeyPatch) -> None:
    # Freeze time
    monkeypatch.setattr("hal.capabilities.scheduling.cron_service.time.time", lambda: 1000.0)
    now = _now_ms()

    assert _compute_next_run(CronSchedule(kind="at", at_ms=now - 1), now) is None
    assert _compute_next_run(CronSchedule(kind="at", at_ms=now + 10), now) == now + 10

    assert _compute_next_run(CronSchedule(kind="every", every_ms=None), now) is None
    assert _compute_next_run(CronSchedule(kind="every", every_ms=0), now) is None
    assert _compute_next_run(CronSchedule(kind="every", every_ms=1000), now) == now + 1000


def test_compute_next_run_cron_invalid_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force croniter to fail
    import croniter as croniter_mod

    monkeypatch.setattr(
        croniter_mod, "croniter", lambda *_args, **_kw: (_ for _ in ()).throw(ValueError())
    )

    assert _compute_next_run(CronSchedule(kind="cron", expr="* * * * *"), 0) is None


@pytest.mark.asyncio
async def test_cron_service_execute_job_updates_state_and_next_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "jobs.json"

    # Freeze time
    monkeypatch.setattr("hal.capabilities.scheduling.cron_service.time.time", lambda: 1000.0)

    service = CronService(store_path=store)
    service.on_job = AsyncMock(return_value="ok")

    job = service.add_job(
        name="j",
        schedule=CronSchedule(kind="every", every_ms=1000),
        message="hi",
    )

    # Make it due
    job.state.next_run_at_ms = _now_ms() - 1

    # Prevent timer re-arming in tests
    monkeypatch.setattr(service, "_arm_timer", lambda: None)

    await service._on_timer()

    assert job.state.last_status == "ok"
    assert job.state.last_error is None
    assert job.state.last_run_at_ms is not None
    assert job.state.next_run_at_ms is not None


@pytest.mark.asyncio
async def test_cron_service_execute_job_error_sets_last_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "jobs.json"
    monkeypatch.setattr("hal.capabilities.scheduling.cron_service.time.time", lambda: 1000.0)

    service = CronService(store_path=store)
    service.on_job = AsyncMock(side_effect=RuntimeError("boom"))

    job = service.add_job(
        name="err",
        schedule=CronSchedule(kind="every", every_ms=1000),
        message="hi",
    )
    job.state.next_run_at_ms = _now_ms() - 1

    monkeypatch.setattr(service, "_arm_timer", lambda: None)

    await service._on_timer()

    assert job.state.last_status == "error"
    assert "boom" in (job.state.last_error or "")
    assert job.state.consecutive_errors == 1


@pytest.mark.asyncio
async def test_cron_service_backoff_on_consecutive_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "jobs.json"
    monkeypatch.setattr("hal.capabilities.scheduling.cron_service.time.time", lambda: 1000.0)

    service = CronService(store_path=store)
    service.on_job = AsyncMock(side_effect=RuntimeError("fail"))

    job = service.add_job(
        name="backoff",
        schedule=CronSchedule(kind="every", every_ms=60_000),
        message="hi",
    )

    monkeypatch.setattr(service, "_arm_timer", lambda: None)

    # First failure: 30s backoff
    job.state.next_run_at_ms = _now_ms() - 1
    await service._on_timer()
    assert job.state.consecutive_errors == 1
    expected_next = _now_ms() + 30 * 1000
    assert job.state.next_run_at_ms == expected_next

    # Second failure: 60s backoff
    job.state.next_run_at_ms = _now_ms() - 1
    await service._on_timer()
    assert job.state.consecutive_errors == 2
    expected_next = _now_ms() + 60 * 1000
    assert job.state.next_run_at_ms == expected_next


@pytest.mark.asyncio
async def test_cron_service_backoff_resets_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "jobs.json"
    monkeypatch.setattr("hal.capabilities.scheduling.cron_service.time.time", lambda: 1000.0)

    call_count = 0

    async def fail_then_succeed(job):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise RuntimeError("fail")

    service = CronService(store_path=store)
    service.on_job = fail_then_succeed

    job = service.add_job(
        name="recover",
        schedule=CronSchedule(kind="every", every_ms=60_000),
        message="hi",
    )

    monkeypatch.setattr(service, "_arm_timer", lambda: None)

    # Two failures
    job.state.next_run_at_ms = _now_ms() - 1
    await service._on_timer()
    job.state.next_run_at_ms = _now_ms() - 1
    await service._on_timer()
    assert job.state.consecutive_errors == 2

    # Third call succeeds
    job.state.next_run_at_ms = _now_ms() - 1
    await service._on_timer()
    assert job.state.consecutive_errors == 0
    assert job.state.last_status == "ok"


@pytest.mark.asyncio
async def test_cron_service_one_shot_jobs_disable_or_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "jobs.json"
    monkeypatch.setattr("hal.capabilities.scheduling.cron_service.time.time", lambda: 1000.0)

    service = CronService(store_path=store, on_job=AsyncMock(return_value=None))

    keep = service.add_job(
        name="keep",
        schedule=CronSchedule(kind="at", at_ms=_now_ms() + 1),
        message="x",
        delete_after_run=False,
    )
    delete = service.add_job(
        name="delete",
        schedule=CronSchedule(kind="at", at_ms=_now_ms() + 1),
        message="y",
        delete_after_run=True,
    )

    # Make both due
    keep.state.next_run_at_ms = _now_ms() - 1
    delete.state.next_run_at_ms = _now_ms() - 1

    monkeypatch.setattr(service, "_arm_timer", lambda: None)

    await service._on_timer()

    assert keep.enabled is False
    assert keep.state.next_run_at_ms is None

    assert all(j.id != delete.id for j in service._store.jobs)  # deleted


@pytest.mark.asyncio
async def test_cron_service_enable_disable_remove_and_run_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "jobs.json"
    monkeypatch.setattr("hal.capabilities.scheduling.cron_service.time.time", lambda: 1000.0)

    service = CronService(store_path=store, on_job=AsyncMock(return_value=None))
    job = service.add_job(
        name="x",
        schedule=CronSchedule(kind="every", every_ms=1000),
        message="hi",
    )

    # Disable
    updated = service.enable_job(job.id, enabled=False)
    assert updated is not None
    assert updated.enabled is False
    assert updated.state.next_run_at_ms is None

    # Run should fail without force
    assert await service.run_job(job.id, force=False) is False

    # Run with force should execute and succeed
    assert await service.run_job(job.id, force=True) is True

    # Remove
    assert service.remove_job(job.id) is True
    assert service.remove_job(job.id) is False


def test_cron_service_load_store_invalid_json(tmp_path: Path) -> None:
    store = tmp_path / "jobs.json"
    store.write_text("{not json", encoding="utf-8")

    service = CronService(store_path=store)
    st = service.status()
    assert st["jobs"] == 0


def test_is_heartbeat_empty_logic() -> None:
    assert _is_heartbeat_empty(None) is True
    assert _is_heartbeat_empty("") is True
    assert _is_heartbeat_empty("\n\n") is True
    assert _is_heartbeat_empty("# Header\n\n") is True
    assert _is_heartbeat_empty("<!-- comment -->\n") is True
    assert _is_heartbeat_empty("- [ ]\n") is True
    assert _is_heartbeat_empty("- [ ] do thing\n") is False


@pytest.mark.asyncio
async def test_heartbeat_tick_skips_empty_and_calls_handler(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()

    called = AsyncMock(return_value=HEARTBEAT_OK_TOKEN)
    hb = HeartbeatService(workspace=ws, on_heartbeat=called, interval_s=0)

    # Empty → no call
    await hb._tick()
    called.assert_not_awaited()

    # Add task → should call handler with prompt
    (ws / "HEARTBEAT.md").write_text("- [ ] do thing\n", encoding="utf-8")
    await hb._tick()

    called.assert_awaited_once_with(HEARTBEAT_PROMPT)


@pytest.mark.asyncio
async def test_heartbeat_start_disabled_does_nothing(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()

    hb = HeartbeatService(workspace=ws, on_heartbeat=AsyncMock(), enabled=False)
    await hb.start()

    assert hb._task is None
    assert hb._running is False


@pytest.mark.asyncio
async def test_trigger_now_returns_response(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()

    called = AsyncMock(return_value=None)
    hb = HeartbeatService(workspace=ws, on_heartbeat=called)

    result = await hb.trigger_now()
    assert result is None


@pytest.mark.asyncio
async def test_trigger_now_without_callback_returns_none(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()

    hb = HeartbeatService(workspace=ws, on_heartbeat=None)
    assert await hb.trigger_now() is None


def test_heartbeat_prompt_constant_has_instructions() -> None:
    assert "HEARTBEAT.md" in HEARTBEAT_PROMPT
    assert HEARTBEAT_OK_TOKEN in HEARTBEAT_PROMPT
