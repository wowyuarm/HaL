"""Workspace-facing repository for session snapshot persistence."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .layout import WorkspaceLayout

_SESSION_FILE_SUFFIX = ".json"


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    """One persisted session snapshot used by background continuation."""

    session_key: str
    channel: str
    chat_id: str
    messages: list[dict[str, Any]]


class SessionRepository:
    """Repository for reading and writing session snapshot files."""

    def __init__(self, workspace: Path):
        self.layout = WorkspaceLayout(workspace)

    def snapshots_dir(self) -> Path:
        """Return directory containing session snapshot files."""
        return self.layout.sessions_dir()

    def snapshot_path(self, session_key: str) -> Path:
        """Resolve one session snapshot file path."""
        return self.snapshots_dir() / f"{_encode_session_key(session_key)}{_SESSION_FILE_SUFFIX}"

    def write_snapshot(
        self,
        *,
        session_key: str,
        channel: str,
        chat_id: str,
        messages: list[dict[str, Any]],
    ) -> Path:
        """Persist one session snapshot."""
        path = self.snapshot_path(session_key)
        payload = {
            "session_key": session_key,
            "channel": channel,
            "chat_id": chat_id,
            "messages": messages,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def read_snapshot(self, session_key: str) -> SessionSnapshot | None:
        """Load one session snapshot when available and valid."""
        path = self.snapshot_path(session_key)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return _parse_snapshot(payload)

    def delete_snapshot(self, session_key: str) -> None:
        """Delete one session snapshot file when it exists."""
        path = self.snapshot_path(session_key)
        if path.is_file():
            path.unlink()


def _encode_session_key(session_key: str) -> str:
    raw = session_key.encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _parse_snapshot(payload: Any) -> SessionSnapshot | None:
    if not isinstance(payload, dict):
        return None
    session_key = payload.get("session_key")
    channel = payload.get("channel")
    chat_id = payload.get("chat_id")
    messages = payload.get("messages")
    if not isinstance(session_key, str):
        return None
    if not isinstance(channel, str):
        return None
    if not isinstance(chat_id, str):
        return None
    if not isinstance(messages, list):
        return None
    normalized_messages = [item for item in messages if isinstance(item, dict)]
    return SessionSnapshot(
        session_key=session_key,
        channel=channel,
        chat_id=chat_id,
        messages=normalized_messages,
    )
