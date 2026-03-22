"""Workspace layout inspection and legacy-path migration helpers."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .layout import WorkspaceLayout

IssueLevel = Literal["info", "warn"]
IssueCategory = Literal["legacy_path", "unmanaged"]
OperationKind = Literal["move_file", "move_dir", "remove_dir"]
OperationStatus = Literal["planned", "applied", "skipped"]

_UNMANAGED_TOP_LEVEL_DIRS = {
    ".mypy_cache": "type-check cache; keep it outside the workspace root if possible",
}

_REMOVABLE_LEGACY_DIRS = {
    "media": "top-level media/ is a legacy path; canonical media now lives under data/media/",
    "data/vectors": "empty data/vectors/ is a leftover from older index layouts",
}


@dataclass(frozen=True, slots=True)
class WorkspaceIssue:
    """One problem or cleanup note discovered during workspace inspection."""

    level: IssueLevel
    category: IssueCategory
    summary: str
    detail: str
    path: Path | None = None


@dataclass(frozen=True, slots=True)
class WorkspaceMigrationOperation:
    """One safe filesystem move from a legacy path to the canonical layout."""

    kind: OperationKind
    source: Path
    target: Path
    reason: str


@dataclass(frozen=True, slots=True)
class WorkspaceMigrationResult:
    """Outcome of applying one migration operation."""

    operation: WorkspaceMigrationOperation
    status: OperationStatus
    detail: str


@dataclass(frozen=True, slots=True)
class WorkspaceDoctorReport:
    """Inspection result for one workspace root."""

    workspace_root: Path
    issues: tuple[WorkspaceIssue, ...]
    operations: tuple[WorkspaceMigrationOperation, ...]


class WorkspaceDoctor:
    """Inspect one workspace root for layout drift and safe migration candidates."""

    def __init__(self, workspace_root: Path) -> None:
        self._layout = WorkspaceLayout(workspace_root.expanduser())

    @property
    def workspace_root(self) -> Path:
        return self._layout.root

    def analyze(self) -> WorkspaceDoctorReport:
        issues: list[WorkspaceIssue] = []
        operations: list[WorkspaceMigrationOperation] = []

        issues.extend(self._detect_legacy_path_issues(operations))
        issues.extend(self._detect_removable_legacy_dirs(operations))
        issues.extend(self._detect_unmanaged_top_level_dirs(operations))

        return WorkspaceDoctorReport(
            workspace_root=self.workspace_root,
            issues=tuple(issues),
            operations=tuple(operations),
        )

    def apply(self, report: WorkspaceDoctorReport | None = None) -> list[WorkspaceMigrationResult]:
        planned = report or self.analyze()
        results: list[WorkspaceMigrationResult] = []
        for operation in planned.operations:
            results.append(self._apply_operation(operation))
        return results

    def _detect_legacy_path_issues(
        self,
        operations: list[WorkspaceMigrationOperation],
    ) -> list[WorkspaceIssue]:
        issues: list[WorkspaceIssue] = []
        for source, target, reason in self._legacy_mappings():
            if not source.exists():
                continue

            if target.exists():
                issues.append(
                    WorkspaceIssue(
                        level="warn",
                        category="legacy_path",
                        summary=f"Legacy path still exists: {source.relative_to(self.workspace_root)}",
                        detail=(
                            f"{reason}. Canonical path already exists at "
                            f"{target.relative_to(self.workspace_root)}, so this needs a manual merge."
                        ),
                        path=source,
                    )
                )
                continue

            operations.append(
                WorkspaceMigrationOperation(
                    kind="move_dir" if source.is_dir() else "move_file",
                    source=source,
                    target=target,
                    reason=reason,
                )
            )
            issues.append(
                WorkspaceIssue(
                    level="warn",
                    category="legacy_path",
                    summary=f"Legacy path can move to canonical location: {source.relative_to(self.workspace_root)}",
                    detail=(
                        f"{reason}. Planned target: {target.relative_to(self.workspace_root)}."
                    ),
                    path=source,
                )
            )
        return issues

    def _legacy_mappings(self) -> list[tuple[Path, Path, str]]:
        root = self.workspace_root
        return [
            (
                root / "config.yaml",
                self._layout.config_file_path(),
                "config.yaml should live under system/",
            ),
            (
                root / "auth.yaml",
                self._layout.auth_file_path(),
                "auth.yaml should live under system/",
            ),
            (
                root / "secrets.yaml",
                self._layout.secrets_file_path(),
                "secrets.yaml should live under system/",
            ),
            (
                root / "skills",
                self._layout.skills_dir(),
                "skills should live under capabilities/skills/",
            ),
            (
                root / "media" / "received",
                self._layout.received_media_dir(),
                "received media should live under data/media/received/",
            ),
        ]

    def _detect_removable_legacy_dirs(
        self,
        operations: list[WorkspaceMigrationOperation],
    ) -> list[WorkspaceIssue]:
        issues: list[WorkspaceIssue] = []
        for relative_path, reason in _REMOVABLE_LEGACY_DIRS.items():
            path = self.workspace_root / relative_path
            if not path.exists() or not path.is_dir() or any(path.iterdir()):
                continue
            operations.append(
                WorkspaceMigrationOperation(
                    kind="remove_dir",
                    source=path,
                    target=path,
                    reason=reason,
                )
            )
            issues.append(
                WorkspaceIssue(
                    level="warn",
                    category="legacy_path",
                    summary=f"Empty legacy directory can be removed: {path.relative_to(self.workspace_root)}",
                    detail=reason,
                    path=path,
                )
            )
        return issues

    def _detect_unmanaged_top_level_dirs(
        self,
        operations: list[WorkspaceMigrationOperation],
    ) -> list[WorkspaceIssue]:
        issues: list[WorkspaceIssue] = []
        for name, detail in _UNMANAGED_TOP_LEVEL_DIRS.items():
            path = self.workspace_root / name
            if not path.exists():
                continue
            issues.append(
                WorkspaceIssue(
                    level="info",
                    category="unmanaged",
                    summary=f"Top-level unmanaged directory present: {name}",
                    detail=detail,
                    path=path,
                )
            )

        legacy_runtime_sessions = self.workspace_root / "runtime" / "sessions"
        if legacy_runtime_sessions.exists():
            if self._is_prunable_legacy_runtime_sessions(legacy_runtime_sessions):
                operations.append(
                    WorkspaceMigrationOperation(
                        kind="remove_dir",
                        source=legacy_runtime_sessions,
                        target=legacy_runtime_sessions,
                        reason=(
                            "runtime/sessions is legacy; detached resume snapshots now live under "
                            "runtime/resume/"
                        ),
                    )
                )
                issues.append(
                    WorkspaceIssue(
                        level="warn",
                        category="legacy_path",
                        summary="Legacy runtime/sessions directory can be removed",
                        detail=(
                            "It only contains stale compatibility state. Detached resume snapshots "
                            "now live under runtime/resume/."
                        ),
                        path=legacy_runtime_sessions,
                    )
                )
                return issues
            issues.append(
                WorkspaceIssue(
                    level="warn",
                    category="legacy_path",
                    summary="Legacy runtime/sessions directory is still present",
                    detail=(
                        "Detached resume snapshots now live under runtime/resume/. "
                        "Review runtime/sessions manually and remove it if no longer needed."
                    ),
                    path=legacy_runtime_sessions,
                )
            )
        return issues

    @staticmethod
    def _is_prunable_legacy_runtime_sessions(path: Path) -> bool:
        entries = sorted(path.iterdir())
        if not entries:
            return True
        if len(entries) != 1:
            return False
        state_file = entries[0]
        if state_file.name != "active_sessions.json" or not state_file.is_file():
            return False
        try:
            content = state_file.read_text(encoding="utf-8").strip()
        except Exception:
            return False
        return content in {"", "{}"}

    def _apply_operation(self, operation: WorkspaceMigrationOperation) -> WorkspaceMigrationResult:
        source = operation.source
        target = operation.target

        if not source.exists():
            return WorkspaceMigrationResult(
                operation=operation,
                status="skipped",
                detail="Source no longer exists.",
            )
        if operation.kind == "remove_dir":
            shutil.rmtree(source)
            return WorkspaceMigrationResult(
                operation=operation,
                status="applied",
                detail="Removed legacy directory.",
            )
        if target.exists():
            return WorkspaceMigrationResult(
                operation=operation,
                status="skipped",
                detail="Target already exists; manual merge required.",
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        return WorkspaceMigrationResult(
            operation=operation,
            status="applied",
            detail="Moved to canonical location.",
        )


__all__ = [
    "WorkspaceDoctor",
    "WorkspaceDoctorReport",
    "WorkspaceIssue",
    "WorkspaceMigrationOperation",
    "WorkspaceMigrationResult",
]
