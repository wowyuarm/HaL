"""Workspace-facing helpers for stable system document discovery."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .layout import WorkspaceLayout


@dataclass(frozen=True, slots=True)
class WorkspaceDocument:
    """One stable workspace document loaded for prompt assembly."""

    name: str
    content: str


class SystemRepository:
    """Repository for stable workspace documents used in system prompts."""

    def __init__(self, workspace: Path) -> None:
        self.layout = WorkspaceLayout(workspace)

    def load_bootstrap_documents(
        self,
        *,
        files: list[str],
    ) -> list[WorkspaceDocument]:
        """Load bootstrap documents from system/ directory."""
        return [
            WorkspaceDocument(name=name, content=content)
            for name in files
            if (content := self._read_document_content(name)) is not None
        ]

    def _read_document_content(self, file_name: str) -> str | None:
        path = self.layout.system_document_path(file_name)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")
