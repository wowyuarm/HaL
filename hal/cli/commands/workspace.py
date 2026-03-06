"""Workspace maintenance commands."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import typer

from hal.workspace import WorkspaceMigrationReport

from .root import app, console


@app.command("workspace-migrate")
def workspace_migrate(
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Apply migration actions. Default runs a dry-run preview only.",
    ),
    workspace: str = typer.Option(
        "",
        "--workspace",
        help="Override workspace path (defaults to config workspace).",
    ),
    report_path: str = typer.Option(
        "",
        "--report",
        help="Optional JSON report output path.",
    ),
    rollback_script: str = typer.Option(
        "",
        "--rollback-script",
        help="Optional rollback shell script output path.",
    ),
) -> None:
    """Plan or apply workspace migration to v3 layout."""
    from hal.infra.config.loader import load_config
    from hal.workspace import (
        export_workspace_migration_report,
        export_workspace_migration_rollback_script,
        migrate_workspace_v3,
    )

    config = load_config()
    root = Path(workspace).expanduser() if workspace else config.workspace_path
    migration_report = migrate_workspace_v3(root, dry_run=not apply)
    _render_migration_summary(
        report=migration_report,
        root=root,
        apply=apply,
    )

    if report_path:
        output_path = Path(report_path).expanduser()
        written_path = export_workspace_migration_report(migration_report, destination=output_path)
        console.print(f"[green]Report written:[/green] {written_path}")

    if rollback_script:
        script_path = Path(rollback_script).expanduser()
        written_script = export_workspace_migration_rollback_script(
            migration_report,
            destination=script_path,
        )
        console.print(f"[green]Rollback script written:[/green] {written_script}")

    _finalize_apply_result(report=migration_report, apply=apply)


def _render_migration_summary(
    *,
    report: WorkspaceMigrationReport,
    root: Path,
    apply: bool,
) -> None:
    """Render migration action summary, warnings, and rollback hints."""
    mode = "apply" if apply else "dry-run"
    console.print(f"[bold]workspace-migrate[/bold] ({mode}) root={root}")

    if not report.actions:
        console.print("[green]No migration actions required.[/green]")
    else:
        for action in report.actions:
            source_text = str(action.source) if action.source else "-"
            console.print(
                f"- [{action.kind}] {source_text} -> {action.destination} ({action.reason})"
            )
        _render_action_counts(report)

    _render_migration_warnings(report)
    _render_rollback_hints(report)


def _render_action_counts(report: WorkspaceMigrationReport) -> None:
    """Render one compact migration action-count summary."""
    counts = Counter(action.kind for action in report.actions)
    console.print(
        f"[bold]Summary:[/bold] move={counts.get('move', 0)} "
        f"mkdir={counts.get('mkdir', 0)} conflict={counts.get('conflict', 0)} "
        f"skip={counts.get('skip', 0)}"
    )


def _render_migration_warnings(report: WorkspaceMigrationReport) -> None:
    """Render migration warnings when present."""
    if not report.warnings:
        return
    console.print("[yellow]Warnings:[/yellow]")
    for warning in report.warnings:
        console.print(f"- {warning}")


def _render_rollback_hints(report: WorkspaceMigrationReport) -> None:
    """Render rollback hints when present."""
    if not report.rollback_hints:
        return
    console.print("[yellow]Rollback hints:[/yellow]")
    for hint in report.rollback_hints:
        console.print(f"- {hint}")


def _finalize_apply_result(*, report: WorkspaceMigrationReport, apply: bool) -> None:
    """Finalize command exit behavior for dry-run and apply modes."""
    if not apply:
        console.print("[cyan]Preview only. Re-run with --apply to execute.[/cyan]")
        return

    if report.applied:
        return

    if report.rolled_back:
        console.print("[red]Migration failed. Applied changes were rolled back.[/red]")
    else:
        console.print("[red]Migration failed before completion.[/red]")
    raise typer.Exit(code=1)
