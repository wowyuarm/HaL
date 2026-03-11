"""Shared command parsing helpers used across channels."""

from __future__ import annotations

from typing import Any

CONTEXT_DEFAULT_MESSAGE = "[context inspection]"
SUPPORTED_SLASH_COMMANDS = frozenset({"brief", "drop", "context"})


def parse_context_command(raw_text: str) -> str:
    """Parse `/context` text into the inspection message."""
    raw = raw_text.strip()
    if not raw:
        return CONTEXT_DEFAULT_MESSAGE

    parts = raw.split(maxsplit=1)
    if len(parts) <= 1:
        return CONTEXT_DEFAULT_MESSAGE

    inspect_message = parts[1].strip()
    return inspect_message or CONTEXT_DEFAULT_MESSAGE


def build_slash_command_text(name: str, args: dict[str, Any] | None = None) -> str:
    """Build a slash-command string from a command name and optional args."""
    command = str(name).strip().lstrip("/")
    if command not in SUPPORTED_SLASH_COMMANDS:
        raise ValueError(f"unsupported command: {name!r}")

    raw_args = ""
    if isinstance(args, dict):
        raw_args = str(args.get("raw", "")).strip()

    return f"/{command} {raw_args}".strip()


__all__ = [
    "CONTEXT_DEFAULT_MESSAGE",
    "SUPPORTED_SLASH_COMMANDS",
    "build_slash_command_text",
    "parse_context_command",
]
