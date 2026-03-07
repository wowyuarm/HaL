"""Protocols and data types for cross-module boundaries.

Defines abstract interfaces that break circular imports between
core modules (e.g. tool_factory ↔ subagent).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from hal.domain.subagent_metadata import SubagentArtifactMetadata, SubagentUsageMetadata


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
