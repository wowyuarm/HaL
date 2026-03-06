"""Workspace-facing repository for legacy conversation log paths."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from .layout import WorkspaceLayout


class LogRepository:
    """Repository for resolving conversation log directory and date files."""

    def __init__(self, workspace: Path):
        self.layout = WorkspaceLayout(workspace)

    def logs_dir(self) -> Path:
        """Return root log directory path."""
        return self.layout.logs_dir()

    def daily_log_path(self, log_date: date) -> Path:
        """Return one daily JSONL log path."""
        return self.layout.daily_log_path(log_date)
