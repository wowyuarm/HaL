"""Workspace-facing repository for context metrics persistence paths."""

from __future__ import annotations

from pathlib import Path

from .layout import WorkspaceLayout


class MetricsRepository:
    """Repository that resolves context metrics storage path for one workspace."""

    def __init__(self, workspace: Path):
        self.layout = WorkspaceLayout(workspace)

    def context_metrics_path(self) -> Path:
        """Return the JSONL path for context metrics."""
        return self.layout.context_metrics_path()
