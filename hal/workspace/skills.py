"""Workspace-facing repository for skill discovery paths."""

from __future__ import annotations

from pathlib import Path

from .layout import WorkspaceLayout

SKILL_FILENAME = "SKILL.md"


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
