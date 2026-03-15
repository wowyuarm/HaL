"""Native aiohttp server for the session-first HaL web runtime."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web
from loguru import logger

from hal.domain.session import SessionManifest
from hal.infra.config.schema import WebConfig

from .bridge import SessionBridge, SessionBusyError
from .protocol import (
    WS_END_SESSION,
    WS_SUBMIT_TURN,
    WS_UPDATE_SCOPE,
    parse_ws_message,
    serialize_event,
    serialize_event_frame,
    serialize_manifest,
    serialize_snapshot,
)

_WS_ROUTE = "/sessions/{session_id}/ws"
_FRONTEND_INDEX = "index.html"
_FRONTEND_ASSETS_DIR = "assets"
_FRONTEND_ASSETS_ROUTE = f"/{_FRONTEND_ASSETS_DIR}/{{asset_path:.*}}"
_FRONTEND_MISSING_MESSAGE = (
    "HaL web frontend bundle not found. Run `npm run build` in ./web before starting `hal web`."
)
_FRONTEND_INDEX_CACHE_CONTROL = "no-store, max-age=0"
_FRONTEND_ASSET_CACHE_CONTROL = "public, max-age=31536000, immutable"


class WebServer:
    """A thin aiohttp server exposing session/thread APIs plus live event WebSockets."""

    def __init__(self, config: WebConfig, bridge: SessionBridge) -> None:
        self._config = config
        self._bridge = bridge
        self._frontend_dist = self._resolve_frontend_dist()
        self._app = web.Application()
        self._app.router.add_get("/", self._serve_frontend_index)
        self._app.router.add_get(f"/{_FRONTEND_INDEX}", self._serve_frontend_index)
        self._app.router.add_get(_FRONTEND_ASSETS_ROUTE, self._serve_frontend_asset)
        self._app.router.add_get("/favicon.ico", self._serve_favicon)
        self._app.router.add_get("/health", self._health)
        self._app.router.add_post("/sessions", self._create_session)
        self._app.router.add_get("/sessions", self._list_sessions)
        self._app.router.add_get("/sessions/{session_id}", self._get_session)
        self._app.router.add_post("/sessions/{session_id}/turns", self._submit_turn)
        self._app.router.add_get("/sessions/{session_id}/events", self._get_events)
        self._app.router.add_post("/sessions/{session_id}/end", self._end_session)
        self._app.router.add_post("/sessions/{session_id}/scope", self._update_scope)
        self._app.router.add_get(_WS_ROUTE, self._session_ws)
        self._app.router.add_get("/threads", self._list_threads)
        self._app.router.add_get("/threads/{slug}", self._get_thread)
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    @property
    def app(self) -> web.Application:
        """Expose the aiohttp application for testing."""
        return self._app

    async def start(self) -> None:
        """Start listening on the configured host/port."""
        if self._runner is not None:
            return
        if self._frontend_dist is None:
            logger.warning(_FRONTEND_MISSING_MESSAGE)
        else:
            logger.info("serving frontend bundle from {}", self._frontend_dist)
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, host=self._config.host, port=self._config.port)
        await self._site.start()
        logger.info(
            "native web server listening on http://{}:{}", self._config.host, self._config.port
        )

    async def stop(self) -> None:
        """Stop the aiohttp server."""
        if self._runner is not None:
            await self._runner.cleanup()
        self._runner = None
        self._site = None

    async def _health(self, request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    async def _serve_frontend_index(self, request: web.Request) -> web.FileResponse:
        frontend_dist = self._require_frontend_dist()
        return self._frontend_file_response(
            frontend_dist / _FRONTEND_INDEX,
            cache_control=_FRONTEND_INDEX_CACHE_CONTROL,
        )

    async def _serve_frontend_asset(self, request: web.Request) -> web.FileResponse:
        frontend_dist = self._require_frontend_dist()
        assets_root = frontend_dist / _FRONTEND_ASSETS_DIR
        asset_path = self._safe_frontend_path(
            assets_root,
            request.match_info.get("asset_path", ""),
        )
        if not asset_path.is_file():
            raise web.HTTPNotFound(text=f"Unknown frontend asset: {request.path}")
        return self._frontend_file_response(
            asset_path,
            cache_control=_FRONTEND_ASSET_CACHE_CONTROL,
        )

    async def _serve_favicon(self, request: web.Request) -> web.StreamResponse:
        if self._frontend_dist is None:
            return web.Response(status=204)
        favicon_path = self._frontend_dist / "favicon.ico"
        if favicon_path.is_file():
            return web.FileResponse(favicon_path)
        return web.Response(status=204)

    async def _create_session(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        manifest = await self._bridge.create_session(
            primary_thread=self._optional_string(payload.get("primary_thread")),
            mounted_threads=self._string_list(payload.get("mounted_threads")),
        )
        return web.json_response({"session": serialize_manifest(manifest)}, status=201)

    async def _list_sessions(self, request: web.Request) -> web.Response:
        thread_slug = self._optional_string(request.query.get("thread_slug"))
        status = self._optional_string(request.query.get("status"))
        sessions = self._bridge.list_sessions(thread_slug=thread_slug, status=status)
        return web.json_response(
            {"sessions": [serialize_manifest(session) for session in sessions]}
        )

    async def _get_session(self, request: web.Request) -> web.Response:
        session_id = request.match_info["session_id"]
        manifest = self._bridge.get_session(session_id)
        if manifest is None:
            raise web.HTTPNotFound(text=f"Unknown session_id: {session_id}")
        return web.json_response({"session": serialize_manifest(manifest)})

    async def _get_events(self, request: web.Request) -> web.Response:
        session_id = request.match_info["session_id"]
        after_seq = self._parse_after_seq(request.query.get("after_seq"))
        self._require_manifest(session_id)
        events = self._bridge.get_events(session_id, after_seq=after_seq)
        return web.json_response({"events": [serialize_event(event) for event in events]})

    async def _submit_turn(self, request: web.Request) -> web.Response:
        session_id = request.match_info["session_id"]
        self._require_manifest(session_id)
        payload = await self._read_json(request)
        content = self._optional_string(payload.get("content"))
        if not content:
            raise web.HTTPBadRequest(text="submit_turn requires non-empty content")
        try:
            submission = await self._bridge.submit_turn(session_id, content)
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        return web.json_response(
            {
                "session": serialize_manifest(submission.manifest),
                "delivery": submission.delivery,
            },
            status=202 if submission.delivery == "intervention_queued" else 200,
        )

    async def _update_scope(self, request: web.Request) -> web.Response:
        session_id = request.match_info["session_id"]
        self._require_manifest(session_id)
        payload = await self._read_json(request)
        try:
            manifest = await self._bridge.update_scope(
                session_id,
                add_threads=self._string_list(payload.get("add_threads")),
                remove_threads=self._string_list(payload.get("remove_threads")),
            )
        except SessionBusyError as exc:
            raise web.HTTPConflict(text=str(exc)) from exc
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        return web.json_response({"session": serialize_manifest(manifest)})

    async def _end_session(self, request: web.Request) -> web.Response:
        session_id = request.match_info["session_id"]
        self._require_manifest(session_id)
        payload = await self._read_json(request)
        reason = self._optional_string(payload.get("reason"))
        if reason not in {"brief", "drop"}:
            raise web.HTTPBadRequest(text="end_session requires reason 'brief' or 'drop'")
        user_prompt = self._optional_string(payload.get("user_prompt")) or ""
        try:
            await self._bridge.end_session(session_id, reason=reason, user_prompt=user_prompt)
        except SessionBusyError as exc:
            raise web.HTTPConflict(text=str(exc)) from exc
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        manifest = self._require_manifest(session_id)
        return web.json_response({"session": serialize_manifest(manifest)})

    async def _list_threads(self, request: web.Request) -> web.Response:
        return web.json_response({"threads": self._bridge.list_threads()})

    async def _get_thread(self, request: web.Request) -> web.Response:
        slug = request.match_info["slug"]
        try:
            thread = self._bridge.get_thread(slug)
        except ValueError as exc:
            raise web.HTTPNotFound(text=str(exc)) from exc
        return web.json_response({"thread": thread})

    async def _session_ws(self, request: web.Request) -> web.StreamResponse:
        session_id = request.match_info["session_id"]
        manifest = self._require_manifest(session_id)
        subscription = await self._bridge.subscribe(session_id)
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_json(serialize_snapshot(manifest, self._bridge.get_events(session_id)))

        pump_task = asyncio.create_task(self._pump_session_events(ws, subscription))
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await self._handle_ws_message(ws, session_id, msg.data)
                elif msg.type == WSMsgType.ERROR:
                    logger.warning("websocket error for {}: {}", session_id, ws.exception())
        finally:
            pump_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pump_task
            await subscription.close()

        return ws

    async def _handle_ws_message(
        self,
        ws: web.WebSocketResponse,
        session_id: str,
        raw: str,
    ) -> None:
        try:
            data = self._decode_json(raw)
            message_type, payload = parse_ws_message(data)
            if message_type == WS_SUBMIT_TURN:
                await self._bridge.submit_turn(session_id, payload["content"])
                return
            if message_type == WS_END_SESSION:
                await self._bridge.end_session(
                    session_id,
                    reason=payload["reason"],
                    user_prompt=payload["user_prompt"],
                )
                return
            if message_type == WS_UPDATE_SCOPE:
                await self._bridge.update_scope(
                    session_id,
                    add_threads=payload["add_threads"],
                    remove_threads=payload["remove_threads"],
                )
                return
        except Exception as exc:
            await ws.send_json({"type": "error", "message": str(exc)})

    async def _pump_session_events(self, ws: web.WebSocketResponse, subscription: Any) -> None:
        while not ws.closed:
            event = await subscription.next_event()
            await ws.send_json(serialize_event_frame(event))

    async def _read_json(self, request: web.Request) -> dict[str, Any]:
        try:
            data = await request.json()
        except Exception as exc:
            raise web.HTTPBadRequest(text="Request body must be valid JSON") from exc
        if not isinstance(data, dict):
            raise web.HTTPBadRequest(text="Request body must be a JSON object")
        return data

    @staticmethod
    def _decode_json(raw: str) -> dict[str, Any]:
        import json

        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("WebSocket payload must be a JSON object")
        return data

    @staticmethod
    def _optional_string(value: Any) -> str | None:
        text = str(value).strip() if value is not None else ""
        return text or None

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @staticmethod
    def _parse_after_seq(value: str | None) -> int:
        if value is None or value == "":
            return 0
        try:
            parsed = int(value)
        except ValueError as exc:
            raise web.HTTPBadRequest(text="after_seq must be an integer") from exc
        return max(parsed, 0)

    def _require_manifest(self, session_id: str) -> SessionManifest:
        manifest = self._bridge.get_session(session_id)
        if manifest is None:
            raise web.HTTPNotFound(text=f"Unknown session_id: {session_id}")
        return manifest

    def _require_frontend_dist(self) -> Path:
        if self._frontend_dist is None:
            raise web.HTTPServiceUnavailable(text=_FRONTEND_MISSING_MESSAGE)
        return self._frontend_dist

    @staticmethod
    def _resolve_frontend_dist() -> Path | None:
        server_file = Path(__file__).resolve()
        candidates = [
            server_file.parents[2] / "web" / "dist",
            server_file.parent / "dist",
        ]
        for candidate in candidates:
            if (candidate / _FRONTEND_INDEX).is_file():
                return candidate
        return None

    @staticmethod
    def _safe_frontend_path(root: Path, relative_path: str) -> Path:
        candidate = (root / relative_path).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError as exc:
            raise web.HTTPNotFound(text="Invalid frontend asset path") from exc
        return candidate

    @staticmethod
    def _frontend_file_response(path: Path, *, cache_control: str) -> web.FileResponse:
        response = web.FileResponse(path)
        response.headers["Cache-Control"] = cache_control
        return response
