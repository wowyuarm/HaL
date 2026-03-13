"""Workspace layout helpers and thin repository wrappers.

All paths follow the canonical workspace contract:
  system/       — identity, instructions, memory, config
  work/         — threads, inbox
  runtime/      — logs, sessions, metrics, cache
  capabilities/ — skills
  data/         — vectors, artifacts, media

Thin repository classes (MetricsRepository, LogRepository, SkillRepository) live
here alongside WorkspaceLayout to keep per-concern wrappers co-located with the
path definitions they delegate to.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

SKILL_FILENAME = "SKILL.md"


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

    def work_sessions_dir(self) -> Path:
        return self.root / "work" / "sessions"

    def session_dir(self, session_id: str) -> Path:
        return self.work_sessions_dir() / session_id

    def session_manifest_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "manifest.json"

    def session_log_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "working-log.jsonl"

    def thread_refs_dir(self, slug: str) -> Path:
        return self.threads_dir() / slug / "refs"

    def skills_dir(self) -> Path:
        return self.root / "capabilities" / "skills"

    def logs_dir(self) -> Path:
        return self.root / "runtime" / "logs"

    def sessions_dir(self) -> Path:
        return self.root / "runtime" / "sessions"

    def resume_dir(self) -> Path:
        return self.root / "runtime" / "resume"

    def session_resume_path(self, session_id: str) -> Path:
        return self.resume_dir() / f"{session_id}.json"

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


# ---------------------------------------------------------------------------
# Thin repository wrappers
# ---------------------------------------------------------------------------


class MetricsRepository:
    """Repository that resolves context metrics storage path for one workspace."""

    def __init__(self, workspace: Path):
        self.layout = WorkspaceLayout(workspace)

    def context_metrics_path(self) -> Path:
        """Return the JSONL path for context metrics."""
        return self.layout.context_metrics_path()


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


class SkillRepository:
    """Repository for resolving skills directory and SKILL.md paths."""

    def __init__(self, workspace: Path):
        self.layout = WorkspaceLayout(workspace)

    def skills_dir(self) -> Path:
        """Return skills root directory path."""
        return self.layout.skills_dir()

    def skill_markdown_path(self, name: str) -> Path:
        """Return one skill markdown path."""
        return self.skills_dir() / name / SKILL_FILENAME
