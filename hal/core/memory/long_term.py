"""Long-term memory — persistent knowledge in MEMORY.md."""

from __future__ import annotations

import re
from pathlib import Path


class LongTermMemory:
    """
    Persistent knowledge that accumulates over time.

    Backed by MEMORY.md — human-readable and editable.
    """

    def __init__(self, memory_file: Path):
        self._file = memory_file

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
        """Extract a specific section by heading."""
        content = self.read()
        if not content:
            return None
        # Match ## heading until next ## or end
        pattern = rf"^##\s+{re.escape(heading)}\s*\n(.*?)(?=^##\s|\Z)"
        match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
        return match.group(1).strip() if match else None

    def update_section(self, heading: str, new_content: str) -> None:
        """Update a specific section, preserving others."""
        content = self.read()
        pattern = rf"(^##\s+{re.escape(heading)}\s*\n).*?(?=^##\s|\Z)"
        replacement = rf"\g<1>{new_content}\n\n"
        new_full = re.sub(pattern, replacement, content, count=1, flags=re.MULTILINE | re.DOTALL)
        if new_full == content:
            # Section not found, append
            new_full = content.rstrip() + f"\n\n## {heading}\n{new_content}\n"
        self.update(new_full)
