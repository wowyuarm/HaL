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
from typing import Any

from aiohttp import web
from loguru import logger

from hal.bus.events import OutboundMessage
from hal.bus.queue import MessageBus
from hal.channels.base import BaseChannel
from hal.infra.config.schema import WebConfig
from hal.workspace.layout import WorkspaceLayout
from hal.workspace.threads import ThreadRepository

from .protocol import (
    build_context_summary,
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
    ) -> None:
        super().__init__(config, bus)
        self.config: WebConfig = config
        self._layout = workspace_layout
        self._threads = ThreadRepository(workspace_layout.root)
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
        except Exception:
            logger.warning("Web client connection lost during send")
            self._ws = None

    # -- WebSocket event callbacks -------------------------------------------

    async def _on_ws_connect(self, ws: web.WebSocketResponse) -> None:
        """Accept a new client; replace any existing connection."""
        old_ws = self._ws
        if old_ws is not None and not old_ws.closed:
            logger.info("Replacing existing web client connection")
            await old_ws.close(code=web.WSCloseCode.GOING_AWAY)

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
            await self._dispatch_command(payload)
        elif msg_type == "select_thread":
            await self._dispatch_select_thread(payload, ws)

    # -- Dispatch helpers ----------------------------------------------------

    async def _dispatch_message(self, payload: dict[str, Any]) -> None:
        """Forward a user text message to the engine via the bus."""
        content = str(payload.get("content", "")).strip()
        if not content:
            return

        await self._handle_message(
            sender_id=_WEB_SENDER_ID,
            chat_id=_WEB_CHAT_ID,
            content=content,
            metadata=self._inbound_metadata(),
        )

    async def _dispatch_command(self, payload: dict[str, Any]) -> None:
        """Forward a slash command to the engine as ``/command_name``."""
        name = str(payload.get("name", "")).strip()
        if not name:
            return
        # Ensure the content starts with a slash so the engine recognizes it.
        content = name if name.startswith("/") else f"/{name}"

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

    # -- Snapshot construction -----------------------------------------------

    async def _push_snapshot(self, ws: web.WebSocketResponse) -> None:
        """Build and send the full state snapshot to one client."""
        thread_entries = self._threads.collect_registry_entries(
            max_entries=_SNAPSHOT_MAX_THREADS,
        )
        snapshot = build_snapshot(
            threads=build_threads(thread_entries),
            history=[],  # Phase 1: no history replay
            context_summary=build_context_summary(),
            status="idle",
            active_thread=self._selected_thread,
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

    @staticmethod
    async def _send_error(ws: web.WebSocketResponse, message: str) -> None:
        """Push an ``error`` frame to the client."""
        try:
            await ws.send_json({"type": "error", "message": message})
        except Exception:
            pass
