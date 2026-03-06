"""Workspace-facing repositories for durable artifact records."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .jsonl import append_jsonl_line
from .layout import WorkspaceLayout


@dataclass(frozen=True, slots=True)
class SubagentExecutionRecord:
    """One durable execution-log row for a completed subagent task."""

    id: str
    timestamp: str
    label: str
    task: str
    iterations: int
    tools_used: list[str]
    tool_call_counts: dict[str, int]
    has_side_effects: bool
    files_modified: list[str]
    commands_run: list[str]
    tool_errors: list[str]
    tokens: int
    result: str
    artifacts: list[str]
    missing_artifacts: list[str]
    status: str


class ArtifactRepository:
    """Repository for workspace artifact records and validations."""

    def __init__(self, workspace: Path) -> None:
        self.layout = WorkspaceLayout(workspace)

    def subagent_log_path(self) -> Path:
        """Return the append-only subagent execution log path."""
        return self.layout.subagent_artifacts_dir() / "subagent-log.jsonl"

    def append_subagent_execution(self, record: SubagentExecutionRecord) -> Path:
        """Append one structured subagent execution record to JSONL."""
        log_path = self.subagent_log_path()
        append_jsonl_line(log_path, json.dumps(asdict(record), ensure_ascii=False))
        return log_path

    @staticmethod
    def partition_existing_markdown_paths(paths: list[Path]) -> tuple[list[Path], list[Path]]:
        """Split candidate paths into existing markdown artifacts vs missing paths."""
        existing = [path for path in paths if path.exists() and path.is_file()]
        missing = [path for path in paths if path not in existing]
        return existing, missing
