"""Registry helpers for discoverable context units."""

from __future__ import annotations

from pathlib import Path

from hal.capabilities.skills.loader import SkillsLoader
from hal.core.context.related import expand_related_slugs
from hal.core.context.units import (
    ContextUnit,
    ContextUnitManifest,
    ThreadContextUnit,
    build_context_units,
    build_skill_unit_manifests,
    build_skill_units,
    build_thread_unit_manifests,
    build_thread_units,
    render_skill_unit_registry_xml,
    render_thread_unit_registry_markdown,
)
from hal.workspace import ThreadRepository

_THREAD_STATUS_ACTIVE = "active"


class ContextRegistry:
    """Registry facade for discoverable skill and thread context units."""

    def __init__(
        self,
        *,
        skills_loader: SkillsLoader,
        thread_repository: ThreadRepository,
        max_thread_registry_size: int,
        related_thread_hops: int = 1,
    ) -> None:
        self._skills_loader = skills_loader
        self._thread_repository = thread_repository
        self._max_thread_registry_size = max(1, max_thread_registry_size)
        self._related_thread_hops = max(1, related_thread_hops)

    @classmethod
    def from_workspace(
        cls,
        *,
        workspace: Path,
        skills_loader: SkillsLoader,
        max_thread_registry_size: int,
        related_thread_hops: int = 1,
    ) -> "ContextRegistry":
        """Build one registry using workspace-backed thread discovery."""
        return cls(
            skills_loader=skills_loader,
            thread_repository=ThreadRepository(workspace),
            max_thread_registry_size=max_thread_registry_size,
            related_thread_hops=related_thread_hops,
        )

    def skill_manifests(self) -> list[ContextUnitManifest]:
        """Return discoverable skill manifests."""
        return build_skill_unit_manifests(self._skills_loader)

    def skill_units(self) -> list[ContextUnit]:
        """Return discoverable skill units."""
        return build_skill_units(self._skills_loader)

    def thread_units(self) -> list[ThreadContextUnit]:
        """Return discoverable thread units."""
        return build_thread_units(
            self._thread_repository,
            max_entries=self._max_thread_registry_size,
        )

    def context_units(self) -> list[ContextUnit]:
        """Return unified context units across skills and threads."""
        units = build_context_units(
            skills_loader=self._skills_loader,
            thread_repository=self._thread_repository,
            max_thread_registry_size=self._max_thread_registry_size,
        )
        return sorted(units, key=lambda unit: (-unit.priority(), unit.key))

    def thread_manifests(self) -> list[ContextUnitManifest]:
        """Return discoverable thread manifests derived from thread registry entries."""
        return build_thread_unit_manifests(
            self._thread_repository,
            max_entries=self._max_thread_registry_size,
        )

    def context_unit_manifests(self) -> list[ContextUnitManifest]:
        """Return the unified registry view across all discoverable context units."""
        return [unit.manifest() for unit in self.context_units()]

    def related_unit_keys(self, key: str) -> tuple[str, ...]:
        """Return keys of units related to the given unit key."""
        for unit in self.context_units():
            if unit.key != key:
                continue
            return unit.related()
        return ()

    @property
    def related_thread_hops(self) -> int:
        """Return configured relation-hop depth for thread expansion."""
        return self._related_thread_hops

    def skill_snapshot(self) -> list[dict[str, object]]:
        """Return JSON-serializable snapshot for runtime skill hints."""
        return [unit.describe() for unit in self.skill_units()]

    def thread_snapshot(self) -> list[dict[str, object]]:
        """Return compact thread snapshot for runtime hinting and matching."""
        return [unit.to_thread_snapshot() for unit in self._thread_units_by_priority()]

    def context_unit_snapshot(self) -> list[dict[str, object]]:
        """Return unified JSON-serializable snapshot for context-unit discovery."""
        return [unit.describe() for unit in self.context_units()]

    def thread_entry_snapshot(self) -> list[dict[str, object]]:
        """Return richer thread entry snapshot for dynamic context rendering."""
        return [unit.to_thread_entry_snapshot() for unit in self._thread_units_by_priority()]

    def active_thread_entry_snapshot(self) -> list[dict[str, object]]:
        """Return dynamic-context entries for active threads only."""
        return [
            entry
            for entry in self.thread_entry_snapshot()
            if entry.get("status") == _THREAD_STATUS_ACTIVE
        ]

    def expand_related_thread_slugs(self, seed_slugs: set[str]) -> set[str]:
        """Expand thread slugs with configured related-thread hop depth."""
        return expand_related_slugs(
            seed_slugs=seed_slugs,
            related_lookup=self.related_unit_keys,
            hops=self._related_thread_hops,
        )

    def render_skill_summary(self) -> str:
        """Render the lightweight XML skill registry."""
        return render_skill_unit_registry_xml(self.skill_manifests())

    def render_thread_summary(self) -> str:
        """Render the lightweight markdown thread registry."""
        return render_thread_unit_registry_markdown(self.thread_manifests())

    def _thread_units_by_priority(self) -> list[ThreadContextUnit]:
        """Return thread units in unified registry priority order."""
        return [unit for unit in self.context_units() if isinstance(unit, ThreadContextUnit)]
