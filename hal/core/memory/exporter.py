"""Daily JSONL → Markdown exporter for memory search indexing.

Converts daily log entries into structured markdown files suitable for
heading-based chunking and semantic search.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from loguru import logger

from hal.core.memory.daily_log import DailyLog, LogEntry


class DailyExporter:
    """Export daily JSONL logs to markdown files for downstream indexing.

    Output format (memory/daily/YYYY-MM-DD.md):
        # 2026-02-12
        ## telegram / 123456
        **[10:30] User**: message text
        **[10:31] Assistant**: response text
        ---
        ## cli / direct
        ...

    Idempotent: skips dates whose .md already exists.
    """

    def __init__(
        self,
        daily_log: DailyLog,
        output_dir: Path,
        *,
        exclude_channels: list[str] | None = None,
    ):
        self._log = daily_log
        self._output_dir = output_dir
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._exclude_channels = {c.strip().lower() for c in (exclude_channels or []) if c.strip()}

    def export_date(self, target_date: date) -> Path | None:
        """Export a single date to markdown. Returns path if written, None if skipped."""
        out_path = self._output_dir / f"{target_date.isoformat()}.md"
        if out_path.exists():
            logger.debug(f"Skipping {target_date} — already exported")
            return None

        entries = self._log.get_all_entries(start_date=target_date, end_date=target_date)
        filtered = self._filter_entries(entries, exclude_channels=self._exclude_channels)
        if not filtered:
            logger.debug(f"No exportable entries for {target_date}")
            return None

        md = self._format_markdown(target_date, filtered)
        out_path.write_text(md, encoding="utf-8")
        logger.info(f"Exported {len(filtered)} entries to {out_path}")
        return out_path

    def export_range(self, start: date, end: date) -> list[Path]:
        """Export a date range (inclusive). Returns list of written paths."""
        paths: list[Path] = []
        current = start
        while current <= end:
            path = self.export_date(current)
            if path:
                paths.append(path)
            current += timedelta(days=1)
        return paths

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _filter_entries(
        entries: list[LogEntry], *, exclude_channels: set[str] | None = None
    ) -> list[LogEntry]:
        """Apply export filtering rules.

        Keep: role in (user, assistant) with entry_type in (message, injection)
        Skip: role=system, role=tool with entry_type != injection
        """
        result: list[LogEntry] = []
        excluded = exclude_channels or set()
        for e in entries:
            if e.channel.lower() in excluded:
                continue
            if e.role == "system":
                continue
            if e.role == "tool" and e.entry_type != "injection":
                continue
            if e.role in ("user", "assistant") or e.entry_type == "injection":
                result.append(e)
        return result

    @staticmethod
    def _format_markdown(target_date: date, entries: list[LogEntry]) -> str:
        """Format filtered entries into markdown grouped by (channel, chat_id)."""
        groups: dict[str, list[LogEntry]] = defaultdict(list)
        for e in entries:
            key = f"{e.channel} / {e.chat_id}"
            groups[key].append(e)

        lines: list[str] = [f"# {target_date.isoformat()}", ""]

        for i, (group_key, group_entries) in enumerate(groups.items()):
            if i > 0:
                lines.append("")
            lines.append(f"## {group_key}")
            lines.append("")

            for j, entry in enumerate(group_entries):
                ts = entry.timestamp[:16].split("T")[-1]  # HH:MM
                role_label = entry.role.capitalize()
                lines.append(f"**[{ts}] {role_label}**: {entry.content}")
                lines.append("")

            # Trailing separator between groups
            if i < len(groups) - 1:
                lines.append("---")

        return "\n".join(lines)
