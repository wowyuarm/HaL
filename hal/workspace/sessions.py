"""Workspace-facing repository for detached loop resume snapshots.

These snapshots are not the session source of truth. Durable manifests and
working logs live under ``work/sessions/{session_id}``; this repository only
stores transient resume payloads in ``runtime/resume/{session_id}.json`` so
background completions can continue the same session after a pause.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .layout import WorkspaceLayout

_SESSION_FILE_SUFFIX = ".json"


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    """One persisted resume snapshot used by background continuation."""

    session_id: str
    channel: str
    chat_id: str
    messages: list[dict[str, Any]]


class SessionRepository:
    """Repository for reading and writing resume snapshot files."""

    def __init__(self, workspace: Path):
        self.layout = WorkspaceLayout(workspace)

    def snapshots_dir(self) -> Path:
        """Return directory containing detached resume snapshot files."""
        return self.layout.resume_dir()

    def snapshot_path(self, session_id: str) -> Path:
        """Resolve one session resume snapshot file path."""
        return self.layout.session_resume_path(session_id)

    def write_snapshot(
        self,
        *,
        session_id: str,
        channel: str,
        chat_id: str,
        messages: list[dict[str, Any]],
    ) -> Path:
        """Persist one detached resume snapshot."""
        path = self.snapshot_path(session_id)
        payload = {
            "session_id": session_id,
            "channel": channel,
            "chat_id": chat_id,
            "messages": messages,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def read_snapshot(self, session_id: str) -> SessionSnapshot | None:
        """Load one resume snapshot when available and valid."""
        path = self.snapshot_path(session_id)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return _parse_snapshot(payload)

    def delete_snapshot(self, session_id: str) -> None:
        """Delete one resume snapshot file when it exists."""
        path = self.snapshot_path(session_id)
        if path.is_file():
            path.unlink()


def _parse_snapshot(payload: Any) -> SessionSnapshot | None:
    if not isinstance(payload, dict):
        return None
    session_id = payload.get("session_id")
    channel = payload.get("channel")
    chat_id = payload.get("chat_id")
    messages = payload.get("messages")
    if not isinstance(session_id, str):
        return None
    if not isinstance(channel, str):
        return None
    if not isinstance(chat_id, str):
        return None
    if not isinstance(messages, list):
        return None
    normalized_messages = [item for item in messages if isinstance(item, dict)]
    return SessionSnapshot(
        session_id=session_id,
        channel=channel,
        chat_id=chat_id,
        messages=normalized_messages,
    )
