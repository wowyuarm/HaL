"""Workspace inspection and migration commands."""

from __future__ import annotations

from pathlib import Path

import typer

from .root import console, workspace_app


def _resolve_workspace_root(workspace: str | None) -> Path:
    if workspace:
        return Path(workspace).expanduser()

    from hal.infra.config.loader import load_config

    return load_config().workspace_path


@workspace_app.command("doctor")
def doctor(
    workspace: str | None = typer.Option(
        None,
        "--workspace",
        help="Workspace root to inspect. Defaults to the configured workspace.",
    ),
) -> None:
    """Inspect workspace layout drift and print safe migration candidates."""
    from hal.workspace.doctor import WorkspaceDoctor

    workspace_root = _resolve_workspace_root(workspace)
    report = WorkspaceDoctor(workspace_root).analyze()

    console.print(f"Workspace: {report.workspace_root}")
    if not report.issues:
        console.print("[green]Workspace layout looks clean.[/green]")
        return

    console.print("\nIssues:")
    for issue in report.issues:
        prefix = "WARN" if issue.level == "warn" else "INFO"
        console.print(f"- [{prefix}] {issue.summary}")
        console.print(f"  {issue.detail}")

    if report.operations:
        console.print("\nPlanned safe moves:")
        for operation in report.operations:
            source = operation.source.relative_to(report.workspace_root)
            target = operation.target.relative_to(report.workspace_root)
            console.print(f"- {source} -> {target}")


@workspace_app.command("migrate")
def migrate(
    workspace: str | None = typer.Option(
        None,
        "--workspace",
        help="Workspace root to migrate. Defaults to the configured workspace.",
    ),
    apply: bool = typer.Option(
        False,
        "--apply/--dry-run",
        help="Apply safe moves. Without --apply, only print the plan.",
    ),
) -> None:
    """Move known legacy paths into the canonical workspace layout."""
    from hal.workspace.doctor import WorkspaceDoctor

    workspace_root = _resolve_workspace_root(workspace)
    doctor = WorkspaceDoctor(workspace_root)
    report = doctor.analyze()

    console.print(f"Workspace: {report.workspace_root}")
    if not report.operations:
        console.print("[green]No safe legacy-path moves are needed.[/green]")
        return

    if not apply:
        console.print("Planned moves:")
        for operation in report.operations:
            source = operation.source.relative_to(report.workspace_root)
            target = operation.target.relative_to(report.workspace_root)
            console.print(f"- {source} -> {target}")
        console.print("\nRun with `--apply` to perform these moves.")
        return

    results = doctor.apply(report)
    console.print("Migration results:")
    for result in results:
        source = result.operation.source.relative_to(report.workspace_root)
        target = result.operation.target.relative_to(report.workspace_root)
        console.print(f"- {result.status.upper()}: {source} -> {target}")
        console.print(f"  {result.detail}")
