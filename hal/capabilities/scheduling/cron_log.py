"""Per-job cron execution log storage."""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from hal.core.memory.daily_log import LogEntry


class CronLog:
    """Single-file JSONL log for a cron job's execution history."""

    def __init__(self, path: Path):
        self.path = path

    def append(self, entry: LogEntry) -> None:
        """Append a log entry."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(entry.model_dump_json() + "\n")

    def get_recent_summaries(self, n: int = 5) -> list[LogEntry]:
        """Read the last N summary entries (entry_type='summary')."""
        if n <= 0:
            return []

        summaries: list[LogEntry] = []
        for entry in self._iter_entries_reverse():
            if entry.entry_type != "summary":
                continue
            summaries.append(entry)
            if len(summaries) >= n:
                break

        summaries.reverse()
        return summaries

    def get_recent_entries(self, n: int) -> list[LogEntry]:
        """Read the last N entries (any type)."""
        if n <= 0:
            return []

        recent: list[LogEntry] = []
        for entry in self._iter_entries_reverse():
            recent.append(entry)
            if len(recent) >= n:
                break

        recent.reverse()
        return recent

    def _iter_entries_reverse(self):
        """Yield parsed entries from newest to oldest."""
        if not self.path.exists():
            return

        try:
            with self.path.open("r", encoding="utf-8") as handle:
                lines = handle.read().splitlines()
        except Exception as exc:
            logger.warning(f"Failed to read cron log {self.path}: {exc}")
            return

        for raw in reversed(lines):
            if not raw.strip():
                continue
            try:
                yield LogEntry.model_validate_json(raw)
            except Exception as exc:
                logger.warning(f"Failed to parse cron log entry in {self.path}: {exc}")
