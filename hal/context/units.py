"""Context-layer unit builders and renderers."""

from __future__ import annotations

from hal.capabilities.skills.loader import SkillsLoader
from hal.domain.context_units import (
    ContextUnit,
    ContextUnitKind,
    ContextUnitManifest,
    SkillContextUnit,
    ThreadContextUnit,
)
from hal.workspace import ThreadRegistryEntry, ThreadRepository


def build_skill_units(loader: SkillsLoader) -> list[SkillContextUnit]:
    """Build discoverable skill units from the skills loader."""
    all_skills = loader.list_skills(filter_unavailable=False)
    available_names = {entry["name"] for entry in loader.list_skills(filter_unavailable=True)}
    units: list[SkillContextUnit] = []
    for skill in all_skills:
        name = str(skill["name"])
        metadata = loader.get_skill_metadata(name) or {}
        units.append(
            SkillContextUnit(
                key=name,
                description=str(metadata.get("description", name)),
                location=str(skill["path"]),
                available=name in available_names,
            )
        )
    return units


def build_thread_units(
    thread_repository: ThreadRepository,
    *,
    max_entries: int,
) -> list[ThreadContextUnit]:
    """Build discoverable thread units from thread registry entries."""
    entries = thread_repository.collect_registry_entries(max_entries=max_entries)
    return [build_thread_context_unit(entry) for entry in entries]


def build_thread_context_unit(entry: ThreadRegistryEntry) -> ThreadContextUnit:
    """Build one thread context unit from a registry entry."""
    return ThreadContextUnit(
        key=entry.slug,
        name=entry.name,
        description=entry.description,
        location=entry.state_path,
        status=entry.status,
        state_content=entry.state_content,
        pinned=entry.pinned,
        mtime=entry.mtime,
        related_threads=entry.related_threads,
        updated_at=entry.updated_at,
        scope=entry.scope,
        core_question=entry.core_question,
        brief_hints=entry.brief_hints,
    )


def build_context_units(
    *,
    skills_loader: SkillsLoader,
    thread_repository: ThreadRepository,
    max_thread_registry_size: int,
) -> list[ContextUnit]:
    """Build unified context units across skills and threads."""
    return [
        *build_skill_units(skills_loader),
        *build_thread_units(thread_repository, max_entries=max_thread_registry_size),
    ]


def build_skill_unit_manifests(loader: SkillsLoader) -> list[ContextUnitManifest]:
    """Build discoverable skill manifests from the skills loader."""
    return [unit.manifest() for unit in build_skill_units(loader)]


def build_thread_unit_manifests(
    thread_repository: ThreadRepository,
    *,
    max_entries: int,
) -> list[ContextUnitManifest]:
    """Build discoverable thread manifests from workspace state files."""
    return [
        unit.manifest() for unit in build_thread_units(thread_repository, max_entries=max_entries)
    ]


def render_skill_unit_registry_xml(manifests: list[ContextUnitManifest]) -> str:
    """Render skill manifests into the existing XML registry format."""
    if not manifests:
        return ""

    def esc(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    lines = ["<skills>"]
    for manifest in manifests:
        lines.append(f'  <skill available="{str(manifest.available).lower()}">')
        lines.append(f"    <name>{esc(manifest.name)}</name>")
        lines.append(f"    <description>{esc(manifest.description)}</description>")
        lines.append(f"    <location>{esc(manifest.location)}</location>")
        lines.append("  </skill>")
    lines.append("</skills>")
    return "\n".join(lines)


def render_thread_unit_registry_markdown(manifests: list[ContextUnitManifest]) -> str:
    """Render thread manifests into a stable markdown registry block."""
    if not manifests:
        return ""

    lines = [
        "# Threads",
        "Known workstreams. Read BRIEF.md when a thread is relevant.",
        "",
    ]
    for manifest in manifests:
        lines.append(f"- **{manifest.key}** — {manifest.name}: {manifest.description}")
    return "\n".join(lines)


__all__ = [
    "ContextUnit",
    "ContextUnitKind",
    "ContextUnitManifest",
    "SkillContextUnit",
    "ThreadContextUnit",
    "build_context_units",
    "build_skill_units",
    "build_thread_units",
    "build_skill_unit_manifests",
    "build_thread_unit_manifests",
    "render_skill_unit_registry_xml",
    "render_thread_unit_registry_markdown",
]
