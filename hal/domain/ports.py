"""Protocols and data types for cross-module boundaries.

Defines abstract interfaces that break circular imports between
core modules (e.g. tool_factory <-> subagent).

Subagent metadata field groups (SubagentUsageMetadata, SubagentArtifactMetadata)
are co-located here alongside SubagentExecutionResult which inherits them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generic, Protocol, TypeVar

ArtifactPathT = TypeVar("ArtifactPathT")


@dataclass(kw_only=True)
class SubagentUsageMetadata:
    """Usage and side-effect metadata emitted by subagent runs."""

    total_tokens: int = 0
    tools_used: list[str] = field(default_factory=list)
    tool_call_counts: dict[str, int] = field(default_factory=dict)
    has_side_effects: bool = False
    files_modified: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    tool_errors: list[str] = field(default_factory=list)


@dataclass(kw_only=True)
class SubagentArtifactMetadata(Generic[ArtifactPathT]):
    """Artifact references emitted by subagent runs."""

    record_id: str | None = None
    artifact_path: ArtifactPathT | None = None
    missing_artifacts: list[ArtifactPathT] = field(default_factory=list)


@dataclass
class SubagentExecutionResult(SubagentArtifactMetadata[Path], SubagentUsageMetadata):
    """Structured subagent execution result."""

    content: str
    artifacts: list[Path] = field(default_factory=list)
    status: str = "completed"
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
        *,
        channel: str | None = None,
        chat_id: str | None = None,
        session_key: str | None = None,
    ) -> str: ...

    def get_running_count(self) -> int: ...

    def get_last_iteration(self) -> int: ...


class ChatProviderPort(Protocol):
    """Minimal chat-completion interface used by core runtime services."""

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> Any: ...


class LLMProviderPort(ChatProviderPort, Protocol):
    """Provider port used when model defaults are required."""

    def get_default_model(self) -> str: ...
