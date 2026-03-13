from __future__ import annotations

import asyncio

import pytest

from hal.domain.events import (
    ASSISTANT_MESSAGE_COMPLETED,
    CONTEXT_COMPILED,
    LOOP_STARTED,
    SESSION_CREATED,
    SESSION_SCOPE_UPDATED,
    TURN_COMPLETED,
    TURN_STARTED,
    USER_MESSAGE,
)


def _create_thread(thread_repo, slug: str, title: str) -> None:
    thread_repo.write_state(
        slug,
        f"# {title}\nStatus: active\n\n## Purpose\nThread for {title}.\n",
    )


@pytest.mark.asyncio
async def test_create_session_emits_session_created(bridge, engine, thread_repo) -> None:
    _create_thread(thread_repo, "auth", "Auth")

    manifest = await bridge.create_session(primary_thread="auth")
    events = engine._session_store.read_events(manifest.session_id)

    assert manifest.primary_thread == "auth"
    assert manifest.mounted_threads == ["auth"]
    assert [event.type for event in events] == [SESSION_CREATED]


@pytest.mark.asyncio
async def test_submit_turn_uses_explicit_session_id_and_persists_turn_events(
    bridge,
    engine,
    thread_repo,
) -> None:
    _create_thread(thread_repo, "auth", "Auth")
    manifest = await bridge.create_session(primary_thread="auth")

    response = await bridge.submit_turn(manifest.session_id, "hello")
    events = engine._session_store.read_events(manifest.session_id)
    event_types = [event.type for event in events]

    assert response == "Final answer"
    assert manifest.turn_count == 1
    assert event_types == [
        SESSION_CREATED,
        TURN_STARTED,
        USER_MESSAGE,
        CONTEXT_COMPILED,
        LOOP_STARTED,
        ASSISTANT_MESSAGE_COMPLETED,
        TURN_COMPLETED,
    ]


@pytest.mark.asyncio
async def test_update_scope_mutates_manifest_and_streams_event(bridge, thread_repo) -> None:
    _create_thread(thread_repo, "auth", "Auth")
    _create_thread(thread_repo, "memory", "Memory")
    manifest = await bridge.create_session(primary_thread="auth")

    subscription = await bridge.subscribe(manifest.session_id)
    try:
        updated = await bridge.update_scope(manifest.session_id, add_threads=["memory"])
        live_event = await asyncio.wait_for(subscription.next_event(), timeout=1)
    finally:
        await subscription.close()

    assert updated.mounted_threads == ["auth", "memory"]
    assert live_event.type == SESSION_SCOPE_UPDATED
    assert live_event.payload["added_threads"] == ["memory"]
