from __future__ import annotations

import asyncio

import pytest

from hal.domain.events import (
    ASSISTANT_MESSAGE_COMPLETED,
    CONTEXT_COMPILED,
    LOOP_STARTED,
    MESSAGE_INJECTED,
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
    assert [event.type for event in events] == [SESSION_CREATED, MESSAGE_INJECTED]


@pytest.mark.asyncio
async def test_submit_turn_uses_explicit_session_id_and_persists_turn_events(
    bridge,
    engine,
    thread_repo,
) -> None:
    _create_thread(thread_repo, "auth", "Auth")
    manifest = await bridge.create_session(primary_thread="auth")

    submission = await bridge.submit_turn(manifest.session_id, "hello")
    events = engine._session_store.read_events(manifest.session_id)
    event_types = [event.type for event in events]

    assert submission.delivery == "turn_started"
    assert submission.manifest.session_id == manifest.session_id
    assert manifest.turn_count == 1
    assert event_types == [
        SESSION_CREATED,
        MESSAGE_INJECTED,
        TURN_STARTED,
        USER_MESSAGE,
        CONTEXT_COMPILED,
        MESSAGE_INJECTED,
        LOOP_STARTED,
        ASSISTANT_MESSAGE_COMPLETED,
        TURN_COMPLETED,
    ]


@pytest.mark.asyncio
async def test_submit_turn_queues_intervention_for_active_session(
    bridge, engine, thread_repo
) -> None:
    _create_thread(thread_repo, "auth", "Auth")
    manifest = await bridge.create_session(primary_thread="auth")
    engine._set_session_active(manifest.session_id, True)

    try:
        submission = await bridge.submit_turn(manifest.session_id, "also cover edge cases")
    finally:
        engine._set_session_active(manifest.session_id, False)

    queued = await asyncio.wait_for(engine.bus.consume_inbound(), timeout=1)
    assert submission.delivery == "intervention_queued"
    assert queued.session_id == manifest.session_id
    assert queued.content == "also cover edge cases"


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


@pytest.mark.asyncio
async def test_removed_scope_thread_no_longer_lists_session_even_if_touched(
    bridge,
    engine,
    thread_repo,
) -> None:
    _create_thread(thread_repo, "auth", "Auth")
    _create_thread(thread_repo, "memory", "Memory")
    manifest = await bridge.create_session(primary_thread="auth", mounted_threads=["memory"])

    engine._mark_threads_touched(manifest.session_id, {"memory"})
    updated = await bridge.update_scope(manifest.session_id, remove_threads=["memory"])

    memory_thread = bridge.get_thread("memory")
    thread_summaries = bridge.list_threads()
    memory_summary = next(thread for thread in thread_summaries if thread["slug"] == "memory")

    assert updated.mounted_threads == ["auth"]
    assert updated.touched_threads == ["memory"]
    assert memory_thread["sessions"] == []
    assert memory_summary["session_counts"] == {}


@pytest.mark.asyncio
async def test_list_threads_orders_by_session_total_desc(bridge, thread_repo) -> None:
    _create_thread(thread_repo, "auth", "Auth")
    _create_thread(thread_repo, "memory", "Memory")
    _create_thread(thread_repo, "search", "Search")

    await bridge.create_session(primary_thread="auth")
    await bridge.create_session(primary_thread="auth")
    await bridge.create_session(primary_thread="memory")

    thread_summaries = bridge.list_threads()

    assert [thread["slug"] for thread in thread_summaries] == ["auth", "memory", "search"]
