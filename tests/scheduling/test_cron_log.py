from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from hal.capabilities.scheduling.cron_log import CronLog
from hal.core.memory.daily_log import LogEntry


def _entry(
    *,
    ts: datetime,
    role: str,
    content: str,
    entry_type: str = "message",
) -> LogEntry:
    return LogEntry(
        timestamp=ts.isoformat(),
        channel="cron",
        chat_id="job1",
        role=role,
        content=content,
        entry_type=entry_type,
        origin="cron",
    )


def test_cron_log_append_and_get_recent_entries(tmp_path: Path) -> None:
    log = CronLog(tmp_path / "cron" / "job1" / "log.jsonl")

    base = datetime(2026, 3, 2, 9, 0, 0)
    log.append(_entry(ts=base, role="user", content="run 1"))
    log.append(_entry(ts=base + timedelta(minutes=1), role="assistant", content="done 1"))
    log.append(_entry(ts=base + timedelta(minutes=2), role="user", content="run 2"))

    recent = log.get_recent_entries(2)
    assert [e.content for e in recent] == ["done 1", "run 2"]


def test_cron_log_get_recent_summaries_filters_from_end(tmp_path: Path) -> None:
    log = CronLog(tmp_path / "cron" / "job1" / "log.jsonl")

    base = datetime(2026, 3, 2, 9, 0, 0)
    log.append(_entry(ts=base, role="assistant", content="normal message"))
    log.append(
        _entry(
            ts=base + timedelta(minutes=1),
            role="user",
            content="[System Summary]\nsummary 1",
            entry_type="summary",
        )
    )
    log.append(_entry(ts=base + timedelta(minutes=2), role="assistant", content="normal message 2"))
    log.append(
        _entry(
            ts=base + timedelta(minutes=3),
            role="user",
            content="[System Summary]\nsummary 2",
            entry_type="summary",
        )
    )

    summaries = log.get_recent_summaries(1)
    assert len(summaries) == 1
    assert summaries[0].content.endswith("summary 2")


def test_cron_log_handles_missing_or_empty_file(tmp_path: Path) -> None:
    log = CronLog(tmp_path / "cron" / "job1" / "log.jsonl")

    assert log.get_recent_entries(5) == []
    assert log.get_recent_summaries(5) == []

    log.path.parent.mkdir(parents=True, exist_ok=True)
    log.path.write_text("", encoding="utf-8")

    assert log.get_recent_entries(5) == []
    assert log.get_recent_summaries(5) == []
