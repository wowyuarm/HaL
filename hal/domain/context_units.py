"""Domain-level semantic models for context-loadable units."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

ContextUnitKind = Literal["skill", "thread"]
_THREAD_STATUS_ACTIVE = "active"


@dataclass(frozen=True, slots=True)
class ContextUnitManifest:
    """One discoverable unit that can contribute to the working set."""

    kind: ContextUnitKind
    key: str
    name: str
    description: str
    location: str
    available: bool = True
    status: str | None = None

    def as_snapshot(self) -> dict[str, str | bool]:
        """Return a JSON-serializable snapshot for prompts and inspectors."""
        snapshot: dict[str, str | bool] = {
            "kind": self.kind,
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "location": self.location,
            "available": self.available,
        }
        if self.status:
            snapshot["status"] = self.status
        return snapshot


class ContextUnit(Protocol):
    """Protocol for any discoverable context-loadable unit."""

    kind: ContextUnitKind
    key: str

    def manifest(self) -> ContextUnitManifest:
        """Project one unit into the stable manifest representation."""

    def describe(self) -> dict[str, object]:
        """Return one lightweight registry description snapshot."""

    def load(self) -> str | None:
        """Load full unit content when needed by runtime logic."""

    def priority(self) -> int:
        """Return unit ranking score used by future loading policies."""

    def related(self) -> tuple[str, ...]:
        """Return keys of units logically related to this one."""


@dataclass(frozen=True, slots=True)
class SkillContextUnit:
    """Skill-backed context unit."""

    key: str
    description: str
    location: str
    available: bool

    kind: ContextUnitKind = "skill"

    def manifest(self) -> ContextUnitManifest:
        return ContextUnitManifest(
            kind="skill",
            key=self.key,
            name=self.key,
            description=self.description,
            location=self.location,
            available=self.available,
        )

    def describe(self) -> dict[str, object]:
        return self.manifest().as_snapshot()

    def load(self) -> str | None:
        from pathlib import Path

        try:
            return Path(self.location).read_text(encoding="utf-8")
        except Exception:
            return None

    def priority(self) -> int:
        return 100 if self.available else 0

    def related(self) -> tuple[str, ...]:
        return ()


@dataclass(frozen=True, slots=True)
class ThreadContextUnit:
    """Thread-backed context unit."""

    key: str
    name: str
    description: str
    location: str
    status: str
    state_content: str
    pinned: bool = False
    mtime: float = 0.0
    related_threads: tuple[str, ...] = ()
    updated_at: str | None = None
    scope: str = ""

    kind: ContextUnitKind = "thread"

    def manifest(self) -> ContextUnitManifest:
        return ContextUnitManifest(
            kind="thread",
            key=self.key,
            name=self.name,
            description=self.description,
            location=self.location,
            available=True,
            status=self.status,
        )

    def describe(self) -> dict[str, object]:
        snapshot = self.manifest().as_snapshot()
        snapshot["pinned"] = self.pinned
        snapshot["mtime"] = self.mtime
        if self.updated_at:
            snapshot["updated_at"] = self.updated_at
        if self.related_threads:
            snapshot["related_threads"] = self.related_threads
        if self.scope:
            snapshot["scope"] = self.scope
        return snapshot

    def load(self) -> str | None:
        return self.state_content or None

    def priority(self) -> int:
        status_score = 200 if self.status == _THREAD_STATUS_ACTIVE else 100
        pin_score = 20 if self.pinned else 0
        return status_score + pin_score

    def related(self) -> tuple[str, ...]:
        return self.related_threads

    def to_thread_snapshot(self) -> dict[str, object]:
        return {
            "slug": self.key,
            "name": self.name,
            "status": self.status,
            "description": self.description,
            "scope": self.scope,
            "state_path": self.location,
            "priority": self.priority(),
            "pinned": self.pinned,
            "related_threads": self.related_threads,
        }

    def to_thread_entry_snapshot(self) -> dict[str, object]:
        return {
            "slug": self.key,
            "name": self.name,
            "status": self.status,
            "description": self.description,
            "scope": self.scope,
            "pinned": self.pinned,
            "state_path": self.location,
            "mtime": self.mtime,
            "state_content": self.state_content,
            "priority": self.priority(),
            "related_threads": self.related_threads,
        }


__all__ = [
    "ContextUnit",
    "ContextUnitKind",
    "ContextUnitManifest",
    "SkillContextUnit",
    "ThreadContextUnit",
]
