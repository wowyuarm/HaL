"""Thread management commands."""

from __future__ import annotations

from pathlib import Path

import typer

from .root import console

thread_app = typer.Typer(help="Manage thread slugs and metadata")


@thread_app.command("migrate-slug")
def migrate_slug(
    old_slug: str = typer.Argument(..., help="Current thread slug"),
    new_slug: str = typer.Argument(..., help="New thread slug"),
    workspace: str | None = typer.Option(
        None,
        "--workspace",
        help="Workspace root. Defaults to the configured workspace.",
    ),
) -> None:
    """Safely migrate a thread slug across directory, manifests, and refs."""
    from hal.workspace.layout import WorkspaceLayout
    from hal.workspace.thread_migrator import (
        MigrationConflict,
        MigrationError,
        ThreadSlugMigrator,
    )

    def _resolve_workspace_root() -> WorkspaceLayout:
        if workspace:
            return WorkspaceLayout(Path(workspace).expanduser())
        from hal.infra.config.loader import load_config

        return WorkspaceLayout(load_config().workspace_path)

    layout = _resolve_workspace_root()
    migrator = ThreadSlugMigrator(layout)

    try:
        migrator.migrate(old_slug, new_slug)
        console.print(f"[green]Thread slug migrated: {old_slug} -> {new_slug}[/green]")
    except MigrationConflict as exc:
        console.print(f"[red]Conflict: {exc}[/red]")
        raise typer.Exit(1)
    except MigrationError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1)
