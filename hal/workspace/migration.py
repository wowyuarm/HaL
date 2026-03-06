"""Workspace v3 migration planning and execution helpers."""

from __future__ import annotations

import json
import shlex
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_DIRECTORY_ACTION_KIND = "mkdir"
_MOVE_ACTION_KIND = "move"
_CONFLICT_ACTION_KIND = "conflict"
_SKIP_ACTION_KIND = "skip"

_SYSTEM_FILE_MOVES = {
    "SOUL.md": "system/SOUL.md",
    "INSTRUCTIONS.md": "system/INSTRUCTIONS.md",
    "MEMORY.md": "system/MEMORY.md",
    "config.yaml": "system/config.yaml",
    "auth.yaml": "system/auth.yaml",
}

_TREE_MOVES = {
    "threads": "work/threads",
    "skills": "capabilities/skills",
    "logs": "runtime/logs",
    "artifacts": "data/artifacts",
}

_LEGACY_MEMORY_MOVES = {
    "memory/MEMORY.md": "system/MEMORY.md",
    "memory/vectors": "data/vectors",
}

_REQUIRED_V3_DIRS = (
    "system",
    "work/threads",
    "work/inbox",
    "runtime/logs",
    "runtime/sessions",
    "runtime/metrics",
    "runtime/cache",
    "capabilities/skills",
    "data/vectors",
    "data/artifacts",
    "data/media",
    "projects",
)


@dataclass(frozen=True, slots=True)
class MigrationAction:
    """One planned workspace migration action."""

    kind: str
    source: Path | None
    destination: Path
    reason: str

    def as_dict(self) -> dict[str, object]:
        """Return JSON-serializable action snapshot."""
        return {
            "kind": self.kind,
            "source": str(self.source) if self.source else None,
            "destination": str(self.destination),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class WorkspaceMigrationReport:
    """Result summary for one workspace migration attempt."""

    root: Path
    actions: tuple[MigrationAction, ...]
    applied: bool
    warnings: tuple[str, ...]
    rolled_back: bool = False
    rollback_hints: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        """Return JSON-serializable migration report."""
        return {
            "generated_at": datetime.now().isoformat(),
            "root": str(self.root),
            "applied": self.applied,
            "rolled_back": self.rolled_back,
            "actions": [action.as_dict() for action in self.actions],
            "warnings": list(self.warnings),
            "rollback_hints": list(self.rollback_hints),
        }


def plan_workspace_v3_migration(root: Path) -> list[MigrationAction]:
    """Plan idempotent actions for migrating one workspace to v3 layout."""
    actions: list[MigrationAction] = []
    move_actions: list[MigrationAction] = []
    move_actions.extend(
        _plan_file_moves(root, _SYSTEM_FILE_MOVES, reason="promote system file to v3 root")
    )
    move_actions.extend(
        _plan_file_moves(root, _TREE_MOVES, reason="promote workspace tree to v3 namespace")
    )
    move_actions.extend(
        _plan_file_moves(
            root,
            _LEGACY_MEMORY_MOVES,
            reason="migrate legacy memory assets into v3 system/data roots",
        )
    )
    planned_move_destinations = {
        action.destination for action in move_actions if action.kind == _MOVE_ACTION_KIND
    }
    actions.extend(
        _plan_required_directories(
            root,
            skip_destinations=planned_move_destinations,
        )
    )
    actions.extend(move_actions)
    return actions


def migrate_workspace_v3(
    root: Path,
    *,
    dry_run: bool = False,
    rollback_on_error: bool = True,
) -> WorkspaceMigrationReport:
    """Apply v3 workspace migration actions (or preview with dry_run)."""
    actions = tuple(plan_workspace_v3_migration(root))
    warnings: list[str] = []
    rollback_hints = _build_rollback_hints(actions)

    if dry_run:
        warnings.extend(_collect_conflict_warnings(actions))
        return WorkspaceMigrationReport(
            root=root,
            actions=actions,
            applied=False,
            warnings=tuple(warnings),
            rolled_back=False,
            rollback_hints=rollback_hints,
        )

    applied_moves: list[MigrationAction] = []
    created_dirs: list[Path] = []

    try:
        for action in actions:
            if action.kind == _DIRECTORY_ACTION_KIND:
                if _ensure_directory(action.destination):
                    created_dirs.append(action.destination)
                continue
            if action.kind == _MOVE_ACTION_KIND:
                _apply_move(action)
                applied_moves.append(action)
                continue
            if action.kind == _CONFLICT_ACTION_KIND:
                warnings.append(
                    f"Skipped move due to existing destination: {action.source} -> {action.destination}"
                )
                continue
    except Exception as exc:
        warnings.append(f"Migration failed: {exc}")
        rolled_back = False
        if rollback_on_error:
            warnings.extend(_rollback_applied_actions(applied_moves, created_dirs))
            rolled_back = True
        return WorkspaceMigrationReport(
            root=root,
            actions=actions,
            applied=False,
            warnings=tuple(warnings),
            rolled_back=rolled_back,
            rollback_hints=rollback_hints,
        )

    return WorkspaceMigrationReport(
        root=root,
        actions=actions,
        applied=True,
        warnings=tuple(warnings),
        rolled_back=False,
        rollback_hints=rollback_hints,
    )


def export_workspace_migration_report(
    report: WorkspaceMigrationReport,
    *,
    destination: Path,
) -> Path:
    """Write one migration report JSON file and return the target path."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report.as_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination


def export_workspace_migration_rollback_script(
    report: WorkspaceMigrationReport,
    *,
    destination: Path,
) -> Path:
    """Write one rollback shell script from migration rollback hints."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "# Generated by hal workspace-migrate",
        f"# Workspace root: {report.root}",
        "",
    ]
    if report.rollback_hints:
        lines.append("# Roll back migration moves in reverse order.")
        for hint in reversed(report.rollback_hints):
            lines.append(hint)
    else:
        lines.append('echo "No rollback actions required."')
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    destination.chmod(0o755)
    return destination


def _plan_required_directories(
    root: Path,
    *,
    skip_destinations: set[Path],
) -> list[MigrationAction]:
    actions: list[MigrationAction] = []
    for relative_path in _REQUIRED_V3_DIRS:
        destination = root / relative_path
        if destination in skip_destinations:
            continue
        if destination.exists():
            continue
        actions.append(
            MigrationAction(
                kind=_DIRECTORY_ACTION_KIND,
                source=None,
                destination=destination,
                reason="ensure required v3 directory exists",
            )
        )
    return actions


def _plan_file_moves(
    root: Path,
    mapping: dict[str, str],
    *,
    reason: str,
) -> list[MigrationAction]:
    actions: list[MigrationAction] = []
    for source_rel, destination_rel in mapping.items():
        source = root / source_rel
        destination = root / destination_rel
        if not source.exists():
            continue
        if destination.exists():
            actions.append(
                MigrationAction(
                    kind=_CONFLICT_ACTION_KIND,
                    source=source,
                    destination=destination,
                    reason=f"{reason} (destination already exists)",
                )
            )
            continue
        actions.append(
            MigrationAction(
                kind=_MOVE_ACTION_KIND,
                source=source,
                destination=destination,
                reason=reason,
            )
        )
    return actions


def _collect_conflict_warnings(actions: tuple[MigrationAction, ...]) -> list[str]:
    warnings: list[str] = []
    for action in actions:
        if action.kind != _CONFLICT_ACTION_KIND:
            continue
        warnings.append(
            f"Planned conflict: destination exists for {action.source} -> {action.destination}"
        )
    return warnings


def _apply_move(action: MigrationAction) -> None:
    source = action.source
    if source is None:
        return
    action.destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(action.destination))


def _ensure_directory(path: Path) -> bool:
    """Ensure one directory exists; return True when created by this call."""
    if path.exists():
        return False
    path.mkdir(parents=True, exist_ok=True)
    return True


def _rollback_applied_actions(
    applied_moves: list[MigrationAction],
    created_dirs: list[Path],
) -> list[str]:
    """Best-effort rollback for already applied migration actions."""
    warnings: list[str] = []

    for action in reversed(applied_moves):
        source = action.source
        if source is None:
            continue
        destination = action.destination
        if not destination.exists():
            warnings.append(
                f"Rollback warning: destination missing, could not restore {destination} -> {source}"
            )
            continue
        if source.exists():
            warnings.append(
                f"Rollback warning: source already exists, could not restore {destination} -> {source}"
            )
            continue
        source.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(destination), str(source))

    for directory in sorted(created_dirs, key=lambda item: len(item.parts), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            continue

    warnings.append("Rollback completed for applied migration actions.")
    return warnings


def _build_rollback_hints(actions: tuple[MigrationAction, ...]) -> tuple[str, ...]:
    """Build shell-friendly rollback hints by reversing move actions."""
    hints: list[str] = []
    for action in actions:
        if action.kind != _MOVE_ACTION_KIND or action.source is None:
            continue
        destination = shlex.quote(str(action.destination))
        source = shlex.quote(str(action.source))
        hints.append(f"mv {destination} {source}")
    return tuple(hints)


__all__ = [
    "export_workspace_migration_rollback_script",
    "export_workspace_migration_report",
    "MigrationAction",
    "WorkspaceMigrationReport",
    "migrate_workspace_v3",
    "plan_workspace_v3_migration",
]
