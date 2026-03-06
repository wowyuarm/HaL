"""CLI command package and Typer app assembly."""

# Import modules for command registration side effects.
from . import anyrouter as _anyrouter  # noqa: F401
from . import gateway as _gateway  # noqa: F401
from . import workspace as _workspace  # noqa: F401
from .root import _resolve_worker_model, app

__all__ = ["app", "_resolve_worker_model"]
