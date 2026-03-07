"""Workspace layout helpers for stable path conventions.

All paths follow the canonical workspace contract:
  system/       — identity, instructions, memory, config
  work/         — threads, inbox
  runtime/      — logs, sessions, metrics, cache
  capabilities/ — skills
  data/         — vectors, artifacts, media
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True, slots=True)
class WorkspaceLayout:
    """Canonical path layout for one HaL workspace root."""

    root: Path

    def system_document_path(self, name: str) -> Path:
        return self.root / "system" / name

    def memory_dir(self) -> Path:
        return self.root / "memory"

    def memory_file_path(self) -> Path:
        return self.root / "system" / "MEMORY.md"

    def threads_dir(self) -> Path:
        return self.root / "work" / "threads"

    def skills_dir(self) -> Path:
        return self.root / "capabilities" / "skills"

    def logs_dir(self) -> Path:
        return self.root / "runtime" / "logs"

    def sessions_dir(self) -> Path:
        return self.root / "runtime" / "sessions"

    def metrics_dir(self) -> Path:
        return self.root / "runtime" / "metrics"

    def daily_log_path(self, log_date: date) -> Path:
        return self.logs_dir() / f"{log_date.isoformat()}.jsonl"

    def events_log_path(self) -> Path:
        return self.logs_dir() / "events.jsonl"

    def context_metrics_path(self) -> Path:
        return self.metrics_dir() / "context_metrics.jsonl"

    def artifacts_dir(self) -> Path:
        return self.root / "data" / "artifacts"

    def subagent_artifacts_dir(self) -> Path:
        return self.artifacts_dir() / "subagent"
