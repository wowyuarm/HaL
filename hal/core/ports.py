"""Protocols and data types for cross-module boundaries.

Defines abstract interfaces that break circular imports between
core modules (e.g. tool_factory ↔ subagent).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class SubagentExecutionResult:
    """Structured subagent execution result."""

    content: str
    artifact_path: Path | None
    total_tokens: int = 0
    record_id: str = ""
    artifacts: list[Path] = field(default_factory=list)
    status: str = "completed"
    has_side_effects: bool = False
    tools_used: list[str] = field(default_factory=list)
    tool_call_counts: dict[str, int] = field(default_factory=dict)
    files_modified: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    tool_errors: list[str] = field(default_factory=list)
    missing_artifacts: list[Path] = field(default_factory=list)
    log_path: Path | None = None


class SubagentPort(Protocol):
    """Minimal interface for subagent management.

    Used by SpawnTool and tool_factory to avoid importing SubagentManager
    directly. SubagentManager satisfies this protocol via structural typing.
    """

    async def run_with_details(
        self,
        task: str,
        label: str | None = None,
    ) -> SubagentExecutionResult: ...

    async def spawn_background(
        self,
        task: str,
        label: str | None = None,
    ) -> str: ...

    def get_running_count(self) -> int: ...

    def get_last_iteration(self) -> int: ...
