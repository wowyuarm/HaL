"""Backend WebSocket channel for the HaL web client.

``WebChannel`` is the ``BaseChannel`` implementation that bridges the engine
message bus to a single browser client over a WebSocket connection.  It owns:

- An aiohttp ``WebSocketServer`` (see ``server.py``)
- Protocol serialization helpers (see ``protocol.py``)
- Thread list discovery via ``WorkspaceLayout`` / ``ThreadRepository``

Phase 1 constraints
~~~~~~~~~~~~~~~~~~~

- **Single client** — only one WebSocket connection is active at a time.
  A new connection replaces (closes) the previous one.
- **No streaming** — outbound messages are complete; token-level deltas
  are deferred to Phase 2.
- **Empty history on connect** — session history replay is not yet wired.
- **select_thread is local** — the channel records the UI selection but
  does not yet change engine context.  Downstream integration depends on
  engine support for thread switching.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from aiohttp import WSCloseCode, web
from loguru import logger

from hal.bus.events import OutboundMessage
from hal.bus.queue import MessageBus
from hal.channels.base import BaseChannel
from hal.channels.commands import (
    CONTEXT_DEFAULT_MESSAGE,
    build_slash_command_text,
    parse_context_command,
)
from hal.infra.config.schema import WebConfig
from hal.workspace.layout import WorkspaceLayout
from hal.workspace.sessions import SessionRepository
from hal.workspace.threads import ThreadRepository

from .protocol import (
    build_context_summary,
    build_history,
    build_snapshot,
    build_threads,
    parse_inbound,
    serialize_outbound,
)
from .server import WebSocketServer

# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

# Default identifiers for the single-user web client.
_WEB_SENDER_ID = "web-client"
_WEB_CHAT_ID = "web"
_WEB_SESSION_KEY = f"{_WEB_CHAT_ID}:{_WEB_CHAT_ID}"

# Max threads returned in the initial snapshot.
_SNAPSHOT_MAX_THREADS = 50

__all__ = ["WebChannel"]


class WebChannel(BaseChannel):
    """Single-client WebSocket channel backed by aiohttp."""

    name = "web"

    def __init__(
        self,
        config: WebConfig,
        bus: MessageBus,
        *,
        workspace_layout: WorkspaceLayout,
        context_inspector: Callable[..., Awaitable[dict[str, object]]] | None = None,
    ) -> None:
        super().__init__(config, bus)
        self.config: WebConfig = config
        self._layout = workspace_layout
        self._threads = ThreadRepository(workspace_layout.root)
        self._session_repository = SessionRepository(workspace_layout.root)
        self._context_inspector = context_inspector
        self._server = WebSocketServer(
            host=config.host,
            port=config.port,
            on_connect=self._on_ws_connect,
            on_disconnect=self._on_ws_disconnect,
            on_message=self._on_ws_message,
        )

        # Active client socket — at most one at a time.
        self._ws: web.WebSocketResponse | None = None
        # UI-selected thread slug (local tracking for Phase 1).
        self._selected_thread: str | None = None
        # Event used to keep start() alive until stop() is called.
        self._stop_event = asyncio.Event()

    # -- BaseChannel interface -----------------------------------------------

    async def start(self) -> None:
        """Start the WebSocket server and block until ``stop()``."""
        if self._running:
            return

        self._running = True
        self._stop_event.clear()
        await self._server.start()
        logger.info(f"Web channel started on {self.config.host}:{self.config.port}")

        # Block so ChannelManager.start_all() keeps us alive.
        try:
            await self._stop_event.wait()
        finally:
            self._running = False

    async def stop(self) -> None:
        """Close the active client and shut down the server."""
        if not self._running:
            return

        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        self._ws = None

        await self._server.stop()
        self._stop_event.set()
        logger.info("Web channel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """Serialize and push one outbound message to the connected client."""
        ws = self._ws
        if ws is None or ws.closed:
            logger.debug("No web client connected — dropping outbound message")
            return

        try:
            await ws.send_json(serialize_outbound(msg))
            if not self._is_progress_message(msg):
                await ws.send_json({"type": "status", "state": "idle"})
                await ws.send_json({"type": "threads", "list": self._build_thread_list()})
                await ws.send_json(
                    {
                        "type": "context_summary",
                        **(await self._build_context_summary_payload()),
                    }
                )
        except Exception:
            logger.warning("Web client connection lost during send")
            self._ws = None

    # -- WebSocket event callbacks -------------------------------------------

    async def _on_ws_connect(self, ws: web.WebSocketResponse) -> None:
        """Accept a new client; replace any existing connection."""
        old_ws = self._ws
        if old_ws is not None and not old_ws.closed:
            logger.info("Replacing existing web client connection")
            await old_ws.close(code=WSCloseCode.GOING_AWAY)

        self._ws = ws
        logger.info("Web client connected")
        await self._push_snapshot(ws)

    async def _on_ws_disconnect(self, ws: web.WebSocketResponse) -> None:
        """Clear the active socket when the current client leaves."""
        if self._ws is ws:
            self._ws = None
            logger.info("Web client disconnected")

    async def _on_ws_message(self, ws: web.WebSocketResponse, raw: str) -> None:
        """Parse and dispatch one inbound client frame."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            await self._send_error(ws, "invalid JSON")
            return

        if not isinstance(data, dict):
            await self._send_error(ws, "payload must be a JSON object")
            return

        try:
            msg_type, payload = parse_inbound(data)
        except ValueError as exc:
            await self._send_error(ws, str(exc))
            return

        if msg_type == "message":
            await self._dispatch_message(payload)
        elif msg_type == "command":
            await self._dispatch_command(payload, ws)
        elif msg_type == "select_thread":
            await self._dispatch_select_thread(payload, ws)

    # -- Dispatch helpers ----------------------------------------------------

    async def _dispatch_message(self, payload: dict[str, Any]) -> None:
        """Forward a user text message to the engine via the bus."""
        content = str(payload.get("content", "")).strip()
        if not content:
            return

        await self._push_status("processing")
        await self._handle_message(
            sender_id=_WEB_SENDER_ID,
            chat_id=_WEB_CHAT_ID,
            content=content,
            metadata=self._inbound_metadata(),
        )

    async def _dispatch_command(
        self, payload: dict[str, Any], ws: web.WebSocketResponse
    ) -> None:
        """Handle a slash command from the web client."""
        name = str(payload.get("name", "")).strip()
        if not name:
            return

        if name == "context":
            await self._dispatch_context_command(payload, ws)
            return

        content = build_slash_command_text(
            name,
            payload.get("args") if isinstance(payload.get("args"), dict) else None,
        )

        await self._push_status("processing")
        await self._handle_message(
            sender_id=_WEB_SENDER_ID,
            chat_id=_WEB_CHAT_ID,
            content=content,
            metadata=self._inbound_metadata(),
        )

    async def _dispatch_select_thread(
        self, payload: dict[str, Any], ws: web.WebSocketResponse
    ) -> None:
        """Record the user's thread selection and re-send the snapshot."""
        slug = str(payload.get("slug", "")).strip()
        if not slug:
            await self._send_error(ws, "select_thread requires a 'slug' field")
            return

        self._selected_thread = slug
        logger.info(f"Web client selected thread: {slug}")
        await self._push_snapshot(ws)

    async def _dispatch_context_command(
        self, payload: dict[str, Any], ws: web.WebSocketResponse
    ) -> None:
        """Build and send a context inspection report directly to the client."""
        if self._context_inspector is None:
            await self._send_error(ws, "context inspector is not configured")
            return

        args = payload.get("args")
        raw = str(args.get("raw", "")).strip() if isinstance(args, dict) else ""
        inspect_message = parse_context_command(
            build_slash_command_text("context", {"raw": raw}) if raw else "/context"
        )
        try:
            context = await self._context_inspector(
                channel=self.name,
                chat_id=_WEB_CHAT_ID,
                current_message=inspect_message,
            )
        except Exception as exc:
            logger.warning(f"web /context failed: {exc}")
            await self._send_error(ws, "failed to build context snapshot")
            return

        await ws.send_json(
            {
                "type": "message",
                "id": f"context_{int(datetime.now(tz=timezone.utc).timestamp() * 1000)}",
                "role": "assistant",
                "content": self._format_context_report(context),
                "ts": datetime.now(tz=timezone.utc).isoformat(),
                "metadata": {},
            }
        )
        await ws.send_json(
            {"type": "context_summary", **(await self._build_context_summary_payload())}
        )

    # -- Snapshot construction -----------------------------------------------

    async def _push_snapshot(self, ws: web.WebSocketResponse) -> None:
        """Build and send the full state snapshot to one client."""
        thread_entries = self._build_thread_list()
        snapshot = build_snapshot(
            threads=thread_entries,
            history=self._build_history(),
            context_summary=await self._build_context_summary_payload(),
            status="idle",
            active_thread=self._selected_thread or (thread_entries[0]["slug"] if thread_entries else None),
        )
        try:
            await ws.send_json(snapshot)
        except Exception:
            logger.warning("Web client connection lost during snapshot push")

    # -- Helpers -------------------------------------------------------------

    def _inbound_metadata(self) -> dict[str, Any]:
        """Build metadata dict attached to every inbound message."""
        meta: dict[str, Any] = {"source": "web"}
        if self._selected_thread:
            meta["selected_thread"] = self._selected_thread
        return meta

    def _build_thread_list(self) -> list[dict[str, Any]]:
        thread_entries = self._threads.collect_registry_entries(
            max_entries=_SNAPSHOT_MAX_THREADS,
        )
        return build_threads(thread_entries)

    def _build_history(self) -> list[dict[str, Any]]:
        snapshot = self._session_repository.read_snapshot(_WEB_SESSION_KEY)
        if snapshot is None:
            return []
        return build_history(snapshot.messages)

    async def _build_context_summary_payload(self) -> dict[str, Any]:
        if self._context_inspector is None:
            return build_context_summary(history=len(self._build_history()))

        try:
            context = await self._context_inspector(
                channel=self.name,
                chat_id=_WEB_CHAT_ID,
                current_message=CONTEXT_DEFAULT_MESSAGE,
            )
        except Exception as exc:
            logger.warning(f"Failed to inspect web context summary: {exc}")
            return build_context_summary(history=len(self._build_history()))

        return build_context_summary(
            tokens=int(context.get("total_input_tokens", 0) or 0),
            tools=int(context.get("tools_count", 0) or 0),
            history=int(context.get("history_message_count", 0) or 0),
        )

    async def _push_status(self, state: str) -> None:
        ws = self._ws
        if ws is None or ws.closed:
            return
        try:
            await ws.send_json({"type": "status", "state": state})
        except Exception:
            self._ws = None

    @staticmethod
    def _is_progress_message(msg: OutboundMessage) -> bool:
        return bool(msg.metadata.get("progress"))

    @staticmethod
    def _format_context_report(payload: dict[str, object]) -> str:
        message_summaries = payload.get("message_summaries")
        lines = [
            "## Context Snapshot",
            "",
            f"- Total input tokens: {payload.get('total_input_tokens', 0)}",
            f"- History messages: {payload.get('history_message_count', 0)}",
            f"- Recall items: {payload.get('recall_count', 0)}",
            f"- Baseline created: {'yes' if payload.get('baseline_created') else 'no'}",
        ]
        if isinstance(message_summaries, list) and message_summaries:
            lines.extend(["", "### Message Preview"])
            for item in message_summaries[:8]:
                if not isinstance(item, dict):
                    continue
                role = str(item.get("role", "")).strip() or "unknown"
                tokens = item.get("tokens", 0)
                preview = str(item.get("preview", "")).strip()
                lines.append(f"- `{role}` ({tokens} tok): {preview}")
        return "\n".join(lines)

    @staticmethod
    async def _send_error(ws: web.WebSocketResponse, message: str) -> None:
        """Push an ``error`` frame to the client."""
        try:
            await ws.send_json({"type": "error", "message": message})
        except Exception:
            pass
