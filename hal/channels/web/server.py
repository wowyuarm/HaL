"""Thin aiohttp WebSocket server for the web channel.

This module owns *only* the HTTP lifecycle.  All domain logic lives in
``WebChannel``; the server delegates connect / disconnect / message events
via callback hooks.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from aiohttp import WSMsgType, web
from loguru import logger

# ---------------------------------------------------------------------------
# Public callback type aliases
# ---------------------------------------------------------------------------

OnConnect = Callable[[web.WebSocketResponse], Awaitable[None]]
OnDisconnect = Callable[[web.WebSocketResponse], Awaitable[None]]
OnMessage = Callable[[web.WebSocketResponse, str], Awaitable[None]]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WS_ROUTE = "/ws"


class WebSocketServer:
    """Minimal aiohttp server exposing a single ``GET /ws`` endpoint."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        on_connect: OnConnect,
        on_disconnect: OnDisconnect,
        on_message: OnMessage,
    ) -> None:
        self._host = host
        self._port = port
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self._on_message = on_message

        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    # -- lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        """Create, bind, and start the HTTP application."""
        if self._runner is not None:
            return  # already running

        self._app = web.Application()
        self._app.router.add_get(_WS_ROUTE, self._ws_handler)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()

        self._site = web.TCPSite(self._runner, host=self._host, port=self._port)
        await self._site.start()
        logger.info(f"WebSocket server listening on ws://{self._host}:{self._port}{_WS_ROUTE}")

    async def stop(self) -> None:
        """Gracefully tear down the HTTP stack."""
        if self._runner is not None:
            await self._runner.cleanup()
        self._site = None
        self._runner = None
        self._app = None

    # -- WebSocket handler ---------------------------------------------------

    async def _ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        """Accept one WebSocket upgrade, relay frames, and handle close."""
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        await self._on_connect(ws)
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await self._on_message(ws, msg.data)
                elif msg.type == WSMsgType.ERROR:
                    logger.warning(f"WebSocket error: {ws.exception()}")
        finally:
            await self._on_disconnect(ws)

        return ws
