"""Tests for DailyExporter — JSONL to Markdown conversion."""

from datetime import date

import pytest

from hal.memory.daily_log import DailyLog, LogEntry
from hal.memory.exporter import DailyExporter


@pytest.fixture
def daily_log(tmp_path):
    return DailyLog(tmp_path / "logs")


@pytest.fixture
def exporter(daily_log, tmp_path):
    return DailyExporter(daily_log, tmp_path / "daily")


def _make_entry(
    channel="telegram",
    chat_id="123",
    role="user",
    content="hello",
    entry_type="message",
    timestamp="2026-02-12T10:30:00",
    tool_name=None,
    tool_result=None,
) -> LogEntry:
    return LogEntry(
        timestamp=timestamp,
        channel=channel,
        chat_id=chat_id,
        role=role,
        content=content,
        entry_type=entry_type,
        tool_name=tool_name,
        tool_result=tool_result,
    )


class TestFilterEntries:
    def test_keeps_user_and_assistant(self):
        entries = [
            _make_entry(role="user", content="hi"),
            _make_entry(role="assistant", content="hello"),
        ]
        result = DailyExporter._filter_entries(entries)
        assert len(result) == 2

    def test_skips_system(self):
        entries = [_make_entry(role="system", content="reset")]
        result = DailyExporter._filter_entries(entries)
        assert len(result) == 0

    def test_skips_tool_messages(self):
        entries = [
            _make_entry(role="tool", content="result", tool_name="exec"),
        ]
        result = DailyExporter._filter_entries(entries)
        assert len(result) == 0

    def test_keeps_injection_entries(self):
        entries = [
            _make_entry(role="user", content="[Subagent Result]", entry_type="injection"),
            _make_entry(role="user", content="[System Summary]", entry_type="injection"),
        ]
        result = DailyExporter._filter_entries(entries)
        assert len(result) == 2

    def test_keeps_tool_injection(self):
        """Tool entries with entry_type=injection should be kept."""
        entries = [
            _make_entry(role="tool", content="injected", entry_type="injection"),
        ]
        result = DailyExporter._filter_entries(entries)
        assert len(result) == 1

    def test_excludes_configured_channels(self):
        entries = [
            _make_entry(channel="cron", chat_id="job1", role="user", content="cron note"),
            _make_entry(channel="telegram", chat_id="123", role="user", content="user note"),
        ]
        result = DailyExporter._filter_entries(entries, exclude_channels={"cron"})
        assert len(result) == 1
        assert result[0].channel == "telegram"


class TestFormatMarkdown:
    def test_groups_by_channel(self):
        entries = [
            _make_entry(channel="telegram", chat_id="123", role="user", content="hi"),
            _make_entry(channel="cli", chat_id="direct", role="assistant", content="hello"),
        ]
        md = DailyExporter._format_markdown(date(2026, 2, 12), entries)
        assert "# 2026-02-12" in md
        assert "## telegram / 123" in md
        assert "## cli / direct" in md

    def test_timestamp_in_output(self):
        entries = [
            _make_entry(timestamp="2026-02-12T10:30:00", content="test"),
        ]
        md = DailyExporter._format_markdown(date(2026, 2, 12), entries)
        assert "**[10:30] User**: test" in md


class TestExportDate:
    def test_empty_log_returns_none(self, exporter):
        result = exporter.export_date(date(2026, 2, 12))
        assert result is None

    def test_exports_markdown(self, daily_log, exporter, tmp_path):
        # Write an entry for 2026-02-12
        log_file = daily_log.data_dir / "2026-02-12.jsonl"
        entry = _make_entry(
            timestamp="2026-02-12T10:30:00",
            channel="telegram",
            chat_id="123",
            role="user",
            content="hello world",
        )
        log_file.write_text(entry.model_dump_json() + "\n")

        path = exporter.export_date(date(2026, 2, 12))
        assert path is not None
        assert path.exists()
        content = path.read_text()
        assert "hello world" in content

    def test_idempotent(self, daily_log, exporter, tmp_path):
        log_file = daily_log.data_dir / "2026-02-12.jsonl"
        entry = _make_entry(timestamp="2026-02-12T10:30:00")
        log_file.write_text(entry.model_dump_json() + "\n")

        path1 = exporter.export_date(date(2026, 2, 12))
        assert path1 is not None

        # Second call should skip (returns None)
        path2 = exporter.export_date(date(2026, 2, 12))
        assert path2 is None


class TestExportRange:
    def test_exports_multiple_dates(self, daily_log, exporter):
        for d in ["2026-02-10", "2026-02-11", "2026-02-12"]:
            log_file = daily_log.data_dir / f"{d}.jsonl"
            entry = _make_entry(timestamp=f"{d}T10:00:00")
            log_file.write_text(entry.model_dump_json() + "\n")

        paths = exporter.export_range(date(2026, 2, 10), date(2026, 2, 12))
        assert len(paths) == 3
