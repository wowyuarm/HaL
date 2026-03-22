"""Root Typer application wiring."""

import typer
from rich.console import Console

from hal import __logo__, __version__

app = typer.Typer(
    name="hal",
    help=f"{__logo__} HaL - Digital Butler",
    no_args_is_help=True,
)
anyrouter_app = typer.Typer(help="Manage AnyRouter bridge")
workspace_app = typer.Typer(help="Inspect and migrate workspace layout")
app.add_typer(anyrouter_app, name="anyrouter")
app.add_typer(workspace_app, name="workspace")

console = Console()

_DEFAULT_MODEL_SENTINEL = "default"


def _resolve_worker_model(primary_model: str, worker_model: str) -> str:
    """Resolve worker model config where 'default' means using the primary model."""
    return primary_model if worker_model == _DEFAULT_MODEL_SENTINEL else worker_model


def version_callback(value: bool):
    """Print version and exit when requested from CLI options."""
    if value:
        console.print(f"{__logo__} hal v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(None, "--version", "-v", callback=version_callback, is_eager=True),
):
    """HaL - Digital Butler."""
    pass
