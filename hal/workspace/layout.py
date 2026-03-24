"""Workspace layout helpers and thin repository wrappers.

All paths follow the canonical workspace contract:
  system/       — identity, instructions, long-term memory, config, auth
  work/         — threads, sessions, inbox
  runtime/      — operational logs, detached resume snapshots, metrics, indexes
  capabilities/ — skills and other capability packages
  data/         — user-facing artifacts and media
  projects/     — optional project working files
  scripts/      — reusable scripts created inside the workspace
  tmp/          — disposable scratch space

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

    def system_dir(self) -> Path:
        return self.root / "system"

    def system_document_path(self, name: str) -> Path:
        return self.system_dir() / name

    def config_file_path(self) -> Path:
        return self.system_dir() / "config.yaml"

    def auth_file_path(self) -> Path:
        return self.system_dir() / "auth.yaml"

    def secrets_file_path(self) -> Path:
        return self.system_dir() / "secrets.yaml"

    def memory_dir(self) -> Path:
        return self.root / "memory"

    def memory_file_path(self) -> Path:
        return self.system_dir() / "MEMORY.md"

    def work_dir(self) -> Path:
        return self.root / "work"

    def threads_dir(self) -> Path:
        return self.work_dir() / "threads"

    def inbox_dir(self) -> Path:
        return self.work_dir() / "inbox"

    def work_sessions_dir(self) -> Path:
        return self.work_dir() / "sessions"

    def session_dir(self, session_id: str) -> Path:
        return self.work_sessions_dir() / session_id

    def session_manifest_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "manifest.json"

    def session_log_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "working-log.jsonl"

    def thread_refs_dir(self, slug: str) -> Path:
        return self.threads_dir() / slug / "refs"

    def capabilities_dir(self) -> Path:
        return self.root / "capabilities"

    def skills_dir(self) -> Path:
        return self.capabilities_dir() / "skills"

    def runtime_dir(self) -> Path:
        return self.root / "runtime"

    def logs_dir(self) -> Path:
        return self.runtime_dir() / "logs"

    def sessions_dir(self) -> Path:
        """Legacy alias kept for background-resume snapshots.

        Native session manifests now live under ``work/sessions``. The
        historical ``runtime/sessions`` bucket has been superseded by
        ``runtime/resume`` for detached loop snapshots, so this helper now
        points there as a compatibility wrapper.
        """
        return self.resume_dir()

    def resume_dir(self) -> Path:
        return self.runtime_dir() / "resume"

    def session_resume_path(self, session_id: str) -> Path:
        return self.resume_dir() / f"{session_id}.json"

    def metrics_dir(self) -> Path:
        return self.runtime_dir() / "metrics"

    def indexes_dir(self) -> Path:
        return self.runtime_dir() / "indexes"

    def daily_log_path(self, log_date: date) -> Path:
        return self.logs_dir() / f"{log_date.isoformat()}.jsonl"

    def events_log_path(self) -> Path:
        return self.logs_dir() / "events.jsonl"

    def context_metrics_path(self) -> Path:
        return self.metrics_dir() / "context_metrics.jsonl"

    def data_dir(self) -> Path:
        return self.root / "data"

    def artifacts_dir(self) -> Path:
        return self.data_dir() / "artifacts"

    def subagent_artifacts_dir(self) -> Path:
        return self.artifacts_dir() / "subagent"

    def media_dir(self) -> Path:
        return self.data_dir() / "media"

    def received_media_dir(self) -> Path:
        return self.media_dir() / "received"

    def web_media_dir(self) -> Path:
        return self.media_dir() / "web"

    def web_session_media_dir(self, session_id: str) -> Path:
        return self.web_media_dir() / session_id

    def projects_dir(self) -> Path:
        return self.root / "projects"

    def scripts_dir(self) -> Path:
        return self.root / "scripts"

    def tmp_dir(self) -> Path:
        return self.root / "tmp"

    def ensure_base_dirs(self) -> None:
        """Create the canonical top-level directories used by the runtime."""
        for path in (
            self.system_dir(),
            self.work_dir(),
            self.threads_dir(),
            self.inbox_dir(),
            self.work_sessions_dir(),
            self.capabilities_dir(),
            self.skills_dir(),
            self.runtime_dir(),
            self.logs_dir(),
            self.resume_dir(),
            self.metrics_dir(),
            self.indexes_dir(),
            self.data_dir(),
            self.media_dir(),
            self.received_media_dir(),
            self.web_media_dir(),
            self.projects_dir(),
            self.scripts_dir(),
            self.tmp_dir(),
            self.subagent_artifacts_dir(),
        ):
            path.mkdir(parents=True, exist_ok=True)


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
