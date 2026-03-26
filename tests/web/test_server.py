from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import web

from hal.infra.config.schema import WebConfig
from hal.web import WebServer
from hal.workspace.thread_state import build_episode_file_name


def _create_thread(thread_repo, slug: str, title: str) -> None:
    thread_repo.write_state(
        slug,
        f"# {title}\nStatus: active\n\n## Purpose\nThread for {title}.\n",
    )


class _FakeRequest:
    def __init__(self, *, payload=None, query=None, match_info=None):
        self._payload = payload if payload is not None else {}
        self.query = query or {}
        self.match_info = match_info or {}

    async def json(self):
        return self._payload


def _decode_response(response) -> dict:
    return json.loads(response.text)


@pytest.mark.asyncio
async def test_http_handler_roundtrip_for_sessions_and_threads(bridge, thread_repo) -> None:
    _create_thread(thread_repo, "auth", "Auth")
    server = WebServer(WebConfig(enabled=True, host="127.0.0.1", port=0), bridge)

    create_response = await server._create_session(  # type: ignore[attr-defined]
        _FakeRequest(payload={"primary_thread": "auth"})
    )
    assert create_response.status == 201
    created = _decode_response(create_response)
    session_id = created["session"]["session_id"]

    session_response = await server._get_session(  # type: ignore[attr-defined]
        _FakeRequest(match_info={"session_id": session_id})
    )
    assert session_response.status == 200
    session_payload = _decode_response(session_response)
    assert session_payload["session"]["primary_thread"] == "auth"

    episode_path = thread_repo.write_episode(
        "auth",
        build_episode_file_name(
            now=datetime(2026, 3, 6, 9, 0, 0),
            session_id=session_id,
            thread_slug="auth",
        ),
        "# 2026-03-06: Auth wrap-up\n\nBody.\n",
    )

    threads_response = await server._list_threads(_FakeRequest())  # type: ignore[attr-defined]
    threads_payload = _decode_response(threads_response)
    assert threads_payload["threads"][0]["slug"] == "auth"
    assert threads_payload["threads"][0]["session_counts"]["active"] == 1

    thread_response = await server._get_thread(  # type: ignore[attr-defined]
        _FakeRequest(match_info={"slug": "auth"})
    )
    thread_payload = _decode_response(thread_response)
    assert thread_payload["thread"]["brief_markdown"].startswith("# Auth")
    assert thread_payload["thread"]["sessions"][0]["session_id"] == session_id
    assert thread_payload["thread"]["episode_refs"][session_id]["thread_slug"] == "auth"
    assert thread_payload["thread"]["episode_refs"][session_id]["episode_rel_path"] == (
        f"episodes/{episode_path.name}"
    )


@pytest.mark.asyncio
async def test_frontend_routes_serve_index_assets_and_static_files(tmp_path, bridge) -> None:
    dist_dir = tmp_path / "dist"
    assets_dir = dist_dir / "assets"
    fonts_dir = dist_dir / "fonts"
    assets_dir.mkdir(parents=True)
    fonts_dir.mkdir(parents=True)
    index_path = dist_dir / "index.html"
    asset_path = assets_dir / "app.js"
    font_path = fonts_dir / "MapleMono-Regular.ttf"
    index_path.write_text("<!doctype html><title>HaL</title>", encoding="utf-8")
    asset_path.write_text("console.log('hal');", encoding="utf-8")
    font_path.write_text("font-data", encoding="utf-8")

    with patch.object(WebServer, "_resolve_frontend_dist", return_value=dist_dir):
        server = WebServer(WebConfig(enabled=True, host="127.0.0.1", port=0), bridge)

    index_response = await server._serve_frontend_index(_FakeRequest())  # type: ignore[attr-defined]
    asset_response = await server._serve_frontend_asset(  # type: ignore[attr-defined]
        _FakeRequest(match_info={"asset_path": "app.js"})
    )
    static_response = await server._serve_frontend_static(  # type: ignore[attr-defined]
        _FakeRequest(match_info={"resource_path": "fonts/MapleMono-Regular.ttf"})
    )

    assert isinstance(index_response, web.FileResponse)
    assert isinstance(asset_response, web.FileResponse)
    assert isinstance(static_response, web.FileResponse)
    assert index_response._path == index_path  # type: ignore[attr-defined]
    assert asset_response._path == asset_path  # type: ignore[attr-defined]
    assert static_response._path == font_path  # type: ignore[attr-defined]
    assert index_response.headers["Cache-Control"] == "no-store, max-age=0"
    assert asset_response.headers["Cache-Control"] == "public, max-age=31536000, immutable"
    assert static_response.headers["Cache-Control"] == "public, max-age=3600"


@pytest.mark.asyncio
async def test_frontend_index_returns_service_unavailable_without_bundle(bridge) -> None:
    with patch.object(WebServer, "_resolve_frontend_dist", return_value=None):
        server = WebServer(WebConfig(enabled=True, host="127.0.0.1", port=0), bridge)

    with pytest.raises(Exception) as exc_info:
        await server._serve_frontend_index(_FakeRequest())  # type: ignore[attr-defined]

    assert getattr(exc_info.value, "status", None) == 503
    assert "npm run build" in getattr(exc_info.value, "text", "")


@pytest.mark.asyncio
async def test_http_scope_update_returns_updated_manifest(bridge, thread_repo) -> None:
    _create_thread(thread_repo, "auth", "Auth")
    _create_thread(thread_repo, "memory", "Memory")
    manifest = await bridge.create_session(primary_thread="auth")
    server = WebServer(WebConfig(enabled=True, host="127.0.0.1", port=0), bridge)

    response = await server._update_scope(  # type: ignore[attr-defined]
        _FakeRequest(
            payload={"add_threads": ["memory"]},
            match_info={"session_id": manifest.session_id},
        )
    )

    assert response.status == 200
    payload = _decode_response(response)
    assert payload["session"]["mounted_threads"] == ["auth", "memory"]


@pytest.mark.asyncio
async def test_http_session_title_update_persists_manifest(bridge, thread_repo) -> None:
    _create_thread(thread_repo, "auth", "Auth")
    manifest = await bridge.create_session(primary_thread="auth")
    server = WebServer(WebConfig(enabled=True, host="127.0.0.1", port=0), bridge)

    response = await server._update_session_title(  # type: ignore[attr-defined]
        _FakeRequest(
            payload={"title": "Planning run"},
            match_info={"session_id": manifest.session_id},
        )
    )

    assert response.status == 200
    payload = _decode_response(response)
    assert payload["session"]["title"] == "Planning run"
    assert bridge.get_session(manifest.session_id).title == "Planning run"


@pytest.mark.asyncio
async def test_http_archive_and_restore_roundtrip_manifest_updates(bridge, thread_repo) -> None:
    _create_thread(thread_repo, "auth", "Auth")
    manifest = await bridge.create_session(primary_thread="auth")
    manifest.status = "ended"
    bridge._engine._session_store.write_manifest(manifest.session_id, manifest)
    server = WebServer(WebConfig(enabled=True, host="127.0.0.1", port=0), bridge)

    archive_response = await server._archive_session(  # type: ignore[attr-defined]
        _FakeRequest(match_info={"session_id": manifest.session_id})
    )
    assert archive_response.status == 200
    archive_payload = _decode_response(archive_response)
    assert archive_payload["session"]["archived_at"] is not None

    thread_response = await server._get_thread(  # type: ignore[attr-defined]
        _FakeRequest(match_info={"slug": "auth"})
    )
    thread_payload = _decode_response(thread_response)
    assert thread_payload["thread"]["sessions"] == []

    restore_response = await server._restore_session(  # type: ignore[attr-defined]
        _FakeRequest(match_info={"session_id": manifest.session_id})
    )
    assert restore_response.status == 200
    restore_payload = _decode_response(restore_response)
    assert restore_payload["session"]["archived_at"] is None


@pytest.mark.asyncio
async def test_http_get_thread_includes_archived_when_requested(bridge, thread_repo) -> None:
    _create_thread(thread_repo, "auth", "Auth")
    manifest = await bridge.create_session(primary_thread="auth")
    manifest.status = "ended"
    manifest.archived_at = "2026-03-26T15:00:00"
    bridge._engine._session_store.write_manifest(manifest.session_id, manifest)
    server = WebServer(WebConfig(enabled=True, host="127.0.0.1", port=0), bridge)

    response = await server._get_thread(  # type: ignore[attr-defined]
        _FakeRequest(match_info={"slug": "auth"}, query={"include_archived": "true"})
    )
    payload = _decode_response(response)
    assert payload["thread"]["sessions"][0]["session_id"] == manifest.session_id


@pytest.mark.asyncio
async def test_http_turn_and_end_handlers_roundtrip_manifest_updates(bridge, thread_repo) -> None:
    _create_thread(thread_repo, "auth", "Auth")
    manifest = await bridge.create_session(primary_thread="auth")
    server = WebServer(WebConfig(enabled=True, host="127.0.0.1", port=0), bridge)

    turn_response = await server._submit_turn(  # type: ignore[attr-defined]
        _FakeRequest(
            payload={"content": "hello"},
            match_info={"session_id": manifest.session_id},
        )
    )
    assert turn_response.status == 200
    turn_payload = _decode_response(turn_response)
    assert turn_payload["delivery"] == "turn_started"
    assert turn_payload["session"]["turn_count"] == 1

    with patch.object(bridge._engine, "_run_session_brief", new_callable=AsyncMock):
        end_response = await server._end_session(  # type: ignore[attr-defined]
            _FakeRequest(
                payload={"reason": "brief"},
                match_info={"session_id": manifest.session_id},
            )
        )
    end_payload = _decode_response(end_response)
    assert end_payload["session"]["status"] == "briefing"


@pytest.mark.asyncio
async def test_http_turn_accepts_attachment_only_submission(bridge, thread_repo) -> None:
    _create_thread(thread_repo, "auth", "Auth")
    manifest = await bridge.create_session(primary_thread="auth")
    server = WebServer(WebConfig(enabled=True, host="127.0.0.1", port=0), bridge)

    response = await server._submit_turn(  # type: ignore[attr-defined]
        _FakeRequest(
            payload={
                "content": "",
                "attachments": [
                    {
                        "type": "image",
                        "name": "diagram.png",
                        "content": [
                            {
                                "type": "image",
                                "image": "data:image/png;base64,ZmFrZQ==",
                                "filename": "diagram.png",
                            }
                        ],
                    }
                ],
            },
            match_info={"session_id": manifest.session_id},
        )
    )

    assert response.status == 200
    events = bridge.get_events(manifest.session_id)
    user_event = next(event for event in events if event.type == "user.message")
    assert user_event.payload["attachment_count"] == 1
    assert user_event.payload["attachments"][0]["type"] == "image"


@pytest.mark.asyncio
async def test_http_thread_episode_endpoint_roundtrips_markdown_and_rejects_traversal(
    bridge,
    thread_repo,
) -> None:
    _create_thread(thread_repo, "auth", "Auth")
    episode_path = thread_repo.write_episode(
        "auth",
        build_episode_file_name(
            now=datetime(2026, 3, 6, 9, 0, 0),
            session_id="s_20260306090000_deadbeef",
            thread_slug="auth",
        ),
        "# 2026-03-06: Auth wrap-up\n\nBody.\n",
    )
    server = WebServer(WebConfig(enabled=True, host="127.0.0.1", port=0), bridge)

    response = await server._get_thread_episode(  # type: ignore[attr-defined]
        _FakeRequest(
            match_info={
                "slug": "auth",
                "episode_rel_path": f"episodes/{episode_path.name}",
            }
        )
    )
    assert response.status == 200
    payload = _decode_response(response)
    assert payload["episode"]["episode_rel_path"] == f"episodes/{episode_path.name}"
    assert payload["episode"]["episode_title"] == "2026-03-06: Auth wrap-up"
    assert payload["episode"]["markdown"].startswith("# 2026-03-06: Auth wrap-up")

    with pytest.raises(Exception) as exc_info:
        await server._get_thread_episode(  # type: ignore[attr-defined]
            _FakeRequest(match_info={"slug": "auth", "episode_rel_path": "../BRIEF.md"})
        )
    assert getattr(exc_info.value, "status", None) == 400


@pytest.mark.asyncio
async def test_http_scope_update_returns_conflict_while_session_is_processing(
    bridge,
    thread_repo,
) -> None:
    _create_thread(thread_repo, "auth", "Auth")
    _create_thread(thread_repo, "memory", "Memory")
    manifest = await bridge.create_session(primary_thread="auth")
    server = WebServer(WebConfig(enabled=True, host="127.0.0.1", port=0), bridge)
    bridge._engine._set_session_active(manifest.session_id, True)

    try:
        with pytest.raises(Exception) as exc_info:
            await server._update_scope(  # type: ignore[attr-defined]
                _FakeRequest(
                    payload={"add_threads": ["memory"]},
                    match_info={"session_id": manifest.session_id},
                )
            )
    finally:
        bridge._engine._set_session_active(manifest.session_id, False)

    assert getattr(exc_info.value, "status", None) == 409


@pytest.mark.asyncio
async def test_ws_message_handler_updates_scope_without_socket(
    bridge,
    thread_repo,
) -> None:
    _create_thread(thread_repo, "auth", "Auth")
    _create_thread(thread_repo, "memory", "Memory")
    manifest = await bridge.create_session(primary_thread="auth")
    server = WebServer(WebConfig(enabled=True, host="127.0.0.1", port=0), bridge)
    ws = AsyncMock()

    await server._handle_ws_message(  # type: ignore[attr-defined]
        ws,
        manifest.session_id,
        json.dumps({"type": "update_scope", "add_threads": ["memory"]}),
    )

    updated = bridge.get_session(manifest.session_id)
    assert updated is not None
    assert updated.mounted_threads == ["auth", "memory"]
    ws.send_json.assert_not_awaited()
