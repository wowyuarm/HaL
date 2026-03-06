"""Shared JSONL filesystem helpers for workspace repositories."""

from __future__ import annotations

from pathlib import Path


def append_jsonl_line(file_path: Path, line: str) -> None:
    """Append one serialized JSON row to a UTF-8 JSONL file."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def read_jsonl_lines(file_path: Path) -> list[str]:
    """Read non-empty JSONL rows from a UTF-8 file, returning stripped lines."""
    if not file_path.exists():
        return []
    with file_path.open("r", encoding="utf-8") as handle:
        return [line.strip() for line in handle if line.strip()]
