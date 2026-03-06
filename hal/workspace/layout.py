"""Workspace layout helpers for stable path conventions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True, slots=True)
class WorkspaceLayout:
    """Canonical path layout for one HaL workspace root."""

    root: Path

    def system_document_path(self, name: str) -> Path:
        v3_path = self.root / "system" / name
        return v3_path if v3_path.exists() else self.root / name

    def memory_dir(self) -> Path:
        return self.root / "memory"

    def memory_file_path(self) -> Path:
        v3_path = self.root / "system" / "MEMORY.md"
        return v3_path if v3_path.exists() else self.memory_dir() / "MEMORY.md"

    def threads_dir(self) -> Path:
        v3_path = self.root / "work" / "threads"
        return v3_path if v3_path.exists() else self.root / "threads"

    def skills_dir(self) -> Path:
        v3_path = self.root / "capabilities" / "skills"
        return v3_path if v3_path.exists() else self.root / "skills"

    def logs_dir(self) -> Path:
        v3_path = self.root / "runtime" / "logs"
        return v3_path if v3_path.exists() else self.root / "logs"

    def sessions_dir(self) -> Path:
        v3_path = self.root / "runtime" / "sessions"
        return v3_path if v3_path.exists() else self.logs_dir() / "sessions"

    def metrics_dir(self) -> Path:
        v3_path = self.root / "runtime" / "metrics"
        return v3_path if v3_path.exists() else self.logs_dir()

    def daily_log_path(self, log_date: date) -> Path:
        return self.logs_dir() / f"{log_date.isoformat()}.jsonl"

    def events_log_path(self) -> Path:
        return self.logs_dir() / "events.jsonl"

    def context_metrics_path(self) -> Path:
        return self.metrics_dir() / "context_metrics.jsonl"

    def artifacts_dir(self) -> Path:
        v3_path = self.root / "data" / "artifacts"
        return v3_path if v3_path.exists() else self.root / "artifacts"

    def subagent_artifacts_dir(self) -> Path:
        return self.artifacts_dir() / "subagent"
