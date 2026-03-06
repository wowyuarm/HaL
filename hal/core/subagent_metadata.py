"""Shared metadata field groups for subagent-related payloads."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

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
