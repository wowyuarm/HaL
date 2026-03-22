"""Workspace-facing repository for stable system MEMORY.md content."""

from __future__ import annotations

import re
from pathlib import Path

from .layout import WorkspaceLayout


class SystemMemoryRepository:
    """Human-editable repository for stable system-level long-term knowledge."""

    def __init__(self, workspace_or_file: Path):
        candidate = Path(workspace_or_file)
        self.layout = None if candidate.name == "MEMORY.md" else WorkspaceLayout(candidate)
        self._file = candidate if candidate.name == "MEMORY.md" else self.layout.memory_file_path()

    @property
    def path(self) -> Path:
        """Return the canonical MEMORY.md path."""
        return self._file

    def read(self) -> str:
        """Read full MEMORY.md content."""
        if self._file.exists():
            return self._file.read_text(encoding="utf-8")
        return ""

    def update(self, content: str) -> None:
        """Write full MEMORY.md content."""
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._file.write_text(content, encoding="utf-8")

    def get_section(self, heading: str) -> str | None:
        """Extract one markdown section by heading."""
        content = self.read()
        if not content:
            return None
        pattern = rf"^##\s+{re.escape(heading)}\s*\n(.*?)(?=^##\s|\Z)"
        match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
        return match.group(1).strip() if match else None

    def update_section(self, heading: str, new_content: str) -> None:
        """Update one markdown section while preserving unrelated content."""
        content = self.read()
        pattern = rf"(^##\s+{re.escape(heading)}\s*\n).*?(?=^##\s|\Z)"
        replacement = rf"\g<1>{new_content}\n\n"
        next_content = re.sub(
            pattern,
            replacement,
            content,
            count=1,
            flags=re.MULTILINE | re.DOTALL,
        )
        if next_content == content:
            next_content = content.rstrip() + f"\n\n## {heading}\n{new_content}\n"
        self.update(next_content)
