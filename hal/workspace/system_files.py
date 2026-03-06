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
        primary_files: list[str],
        legacy_files: list[str],
    ) -> list[WorkspaceDocument]:
        """Load primary bootstrap docs, falling back to legacy docs when needed."""
        documents = self._read_existing_documents(primary_files)
        instructions_path = self.layout.system_document_path("INSTRUCTIONS.md")
        if instructions_path.exists():
            return documents
        return documents + self._read_existing_documents(legacy_files)

    def _read_existing_documents(self, file_names: list[str]) -> list[WorkspaceDocument]:
        """Load existing UTF-8 markdown/text docs in listed order."""
        return [
            WorkspaceDocument(name=file_name, content=content)
            for file_name in file_names
            if (content := self._read_document_content(file_name)) is not None
        ]

    def _read_document_content(self, file_name: str) -> str | None:
        path = self.layout.system_document_path(file_name)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")
