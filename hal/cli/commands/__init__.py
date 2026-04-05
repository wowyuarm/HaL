"""CLI command package and Typer app assembly."""

# Import modules for command registration side effects.
from . import anyrouter as _anyrouter  # noqa: F401
from . import gateway as _gateway  # noqa: F401
from . import web as _web  # noqa: F401
from . import workspace as _workspace  # noqa: F401
from .root import _resolve_worker_model, app
from .thread import thread_app

app.add_typer(thread_app, name="thread")

__all__ = ["app", "_resolve_worker_model"]
