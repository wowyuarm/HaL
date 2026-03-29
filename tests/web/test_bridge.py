from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from hal.domain.events import (
    ASSISTANT_MESSAGE_COMPLETED,
    CONTEXT_COMPILED,
    LOOP_STARTED,
    MESSAGE_INJECTED,
    SESSION_CREATED,
    SESSION_SCOPE_UPDATED,
    STATUS_CHANGED,
    TURN_COMPLETED,
    TURN_STARTED,
    USER_MESSAGE,
)
from hal.workspace.thread_state import build_episode_file_name


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
async def test_update_session_title_persists_manifest(bridge, engine, thread_repo) -> None:
    _create_thread(thread_repo, "auth", "Auth")
    manifest = await bridge.create_session(primary_thread="auth")

    updated = await bridge.update_session_title(manifest.session_id, "  规划v2阶段3  ")
    persisted = engine._session_store.read_manifest(manifest.session_id)

    assert updated.title == "规划 v2 阶段 3"
    assert persisted is not None
    assert persisted.title == "规划 v2 阶段 3"


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

    queued = engine._drain_pending_for_session(session_id=manifest.session_id)
    assert submission.delivery == "intervention_queued"
    assert len(queued) == 1
    assert queued[0].session_id == manifest.session_id
    assert queued[0].content == "also cover edge cases"


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
async def test_brief_start_streams_transient_status_change(bridge, thread_repo) -> None:
    _create_thread(thread_repo, "auth", "Auth")
    manifest = await bridge.create_session(primary_thread="auth")

    subscription = await bridge.subscribe(manifest.session_id)
    with patch.object(bridge._engine, "_run_session_brief", new_callable=AsyncMock):
        try:
            updated = await bridge.end_session(manifest.session_id, reason="brief")
            live_event = await asyncio.wait_for(subscription.next_event(), timeout=1)
        finally:
            await subscription.close()

    assert updated == "/brief"
    assert live_event.type == STATUS_CHANGED
    assert live_event.payload["status"] == "briefing"
    assert live_event.payload["kind"] == "session_brief_start"


@pytest.mark.asyncio
async def test_archive_session_marks_terminal_manifest(bridge, engine, thread_repo) -> None:
    _create_thread(thread_repo, "auth", "Auth")
    manifest = await bridge.create_session(primary_thread="auth")
    manifest.status = "ended"
    engine._session_store.write_manifest(manifest.session_id, manifest)

    archived = await bridge.archive_session(manifest.session_id)

    assert archived.archived_at is not None
    thread = bridge.get_thread("auth")
    assert thread["sessions"] == []
    with_archived = bridge.get_thread("auth", include_archived=True)
    assert with_archived["sessions"][0]["session_id"] == manifest.session_id


@pytest.mark.asyncio
async def test_restore_session_reappears_in_default_thread_listing(bridge, engine, thread_repo) -> None:
    _create_thread(thread_repo, "auth", "Auth")
    manifest = await bridge.create_session(primary_thread="auth")
    manifest.status = "ended"
    manifest.archived_at = "2026-03-26T15:00:00"
    engine._session_store.write_manifest(manifest.session_id, manifest)

    restored = await bridge.restore_session(manifest.session_id)

    assert restored.archived_at is None
    thread = bridge.get_thread("auth")
    assert thread["sessions"][0]["session_id"] == manifest.session_id


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
async def test_thread_detail_exposes_episode_refs_for_briefed_sessions(
    bridge,
    thread_repo,
) -> None:
    _create_thread(thread_repo, "auth", "Auth")
    manifest = await bridge.create_session(primary_thread="auth")
    episode_markdown = "# 2026-03-06: Auth wrap-up\n\nBody.\n"
    episode_path = thread_repo.write_episode(
        "auth",
        build_episode_file_name(
            now=datetime(2026, 3, 6, 9, 0, 0),
            session_id=manifest.session_id,
            thread_slug="auth",
        ),
        episode_markdown,
    )

    thread = bridge.get_thread("auth")
    episode_ref = thread["episode_refs"][manifest.session_id]

    assert episode_ref["thread_slug"] == "auth"
    assert episode_path.name == episode_ref["episode_rel_path"].split("/")[-1]
    assert episode_ref["episode_title"] == "2026-03-06: Auth wrap-up"


@pytest.mark.asyncio
async def test_thread_detail_prefers_cross_thread_episode_for_matching_session(
    bridge,
    thread_repo,
) -> None:
    _create_thread(thread_repo, "hal-project", "HaL Project")
    _create_thread(thread_repo, "hal-web-design", "HaL Web Design")
    manifest = await bridge.create_session(
        primary_thread="hal-project",
        mounted_threads=["hal-web-design"],
    )
    manifest.status = "ended"
    engine_manifest = bridge._engine._session_store.read_manifest(manifest.session_id)
    assert engine_manifest is not None
    engine_manifest.status = "ended"
    bridge._engine._session_store.write_manifest(manifest.session_id, engine_manifest)
    episode_path = thread_repo.write_episode(
        "hal-web-design",
        build_episode_file_name(
            now=datetime(2026, 3, 6, 9, 0, 0),
            session_id=manifest.session_id,
            thread_slug="hal-web-design",
        ),
        "# 2026-03-06: Web design wrap-up\n\nBody.\n",
    )

    thread = bridge.get_thread("hal-project")
    episode_ref = thread["episode_refs"][manifest.session_id]

    assert episode_ref["thread_slug"] == "hal-web-design"
    assert episode_ref["episode_rel_path"] == f"episodes/{episode_path.name}"
    assert episode_ref["episode_title"] == "2026-03-06: Web design wrap-up"


@pytest.mark.asyncio
async def test_thread_episode_reader_returns_markdown_and_rejects_traversal(
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

    episode = bridge.get_thread_episode("auth", f"episodes/{episode_path.name}")
    assert episode["episode_rel_path"] == f"episodes/{episode_path.name}"
    assert episode["episode_title"] == "2026-03-06: Auth wrap-up"
    assert episode["markdown"].startswith("# 2026-03-06: Auth wrap-up")

    with pytest.raises(ValueError):
        bridge.get_thread_episode("auth", "../BRIEF.md")


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
