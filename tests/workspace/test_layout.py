from __future__ import annotations

from datetime import date
from pathlib import Path

from hal.workspace import WorkspaceLayout


def test_workspace_layout_builds_runtime_paths(tmp_path: Path) -> None:
    layout = WorkspaceLayout(tmp_path)

    assert layout.logs_dir() == tmp_path / "runtime" / "logs"
    assert layout.sessions_dir() == tmp_path / "runtime" / "sessions"
    assert layout.metrics_dir() == tmp_path / "runtime" / "metrics"
    assert layout.events_log_path() == tmp_path / "runtime" / "logs" / "events.jsonl"
    assert layout.context_metrics_path() == (
        tmp_path / "runtime" / "metrics" / "context_metrics.jsonl"
    )
    assert layout.daily_log_path(date(2026, 3, 6)) == (
        tmp_path / "runtime" / "logs" / "2026-03-06.jsonl"
    )


def test_workspace_layout_builds_domain_paths(tmp_path: Path) -> None:
    layout = WorkspaceLayout(tmp_path)

    assert layout.memory_file_path() == tmp_path / "system" / "MEMORY.md"
    assert layout.threads_dir() == tmp_path / "work" / "threads"
    assert layout.skills_dir() == tmp_path / "capabilities" / "skills"
    assert layout.subagent_artifacts_dir() == tmp_path / "data" / "artifacts" / "subagent"
    assert layout.system_document_path("SOUL.md") == tmp_path / "system" / "SOUL.md"
    assert layout.artifacts_dir() == tmp_path / "data" / "artifacts"
