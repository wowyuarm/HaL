"""Tests for domain session models, event types, and event publisher."""

from __future__ import annotations

import pytest

from hal.domain.event_sink import SessionEventPublisher, SessionEventSink
from hal.domain.events import (
    ASSISTANT_CHUNK,
    EVENT_SCHEMA_VERSION,
    SESSION_CREATED,
    TOOL_CALL_COMPLETED,
    TRANSIENT_TYPES,
    TURN_STARTED,
    SessionEvent,
    is_durable,
)
from hal.domain.session import (
    SessionManifest,
    SessionRuntimeState,
    build_session_id,
    build_turn_id,
)

# ---------------------------------------------------------------------------
# SessionEvent
# ---------------------------------------------------------------------------


class TestSessionEvent:
    def test_schema_version_default(self) -> None:
        event = SessionEvent(seq=1, session_id="s_test", type=SESSION_CREATED, actor="engine")
        assert event.v == EVENT_SCHEMA_VERSION

    def test_json_roundtrip(self) -> None:
        event = SessionEvent(
            seq=42,
            session_id="s_test",
            turn_id="t_0001",
            type=TOOL_CALL_COMPLETED,
            actor="tool",
            refs={"tool_call_id": "tc_1"},
            payload={"name": "fs_read", "duration_ms": 120},
        )
        raw = event.model_dump_json()
        restored = SessionEvent.model_validate_json(raw)
        assert restored.seq == 42
        assert restored.type == TOOL_CALL_COMPLETED
        assert restored.refs["tool_call_id"] == "tc_1"
        assert restored.payload["name"] == "fs_read"


# ---------------------------------------------------------------------------
# Event type helpers
# ---------------------------------------------------------------------------


class TestEventTypes:
    def test_durable_types(self) -> None:
        assert is_durable(SESSION_CREATED) is True
        assert is_durable(TURN_STARTED) is True
        assert is_durable(TOOL_CALL_COMPLETED) is True

    def test_transient_types(self) -> None:
        assert is_durable(ASSISTANT_CHUNK) is False
        for t in TRANSIENT_TYPES:
            assert is_durable(t) is False


# ---------------------------------------------------------------------------
# SessionManifest
# ---------------------------------------------------------------------------


class TestSessionManifest:
    def test_defaults(self) -> None:
        m = SessionManifest(session_id="s_test")
        assert m.status == "active"
        assert m.primary_thread is None
        assert m.mounted_threads == []
        assert m.turn_count == 0

    def test_json_roundtrip(self) -> None:
        m = SessionManifest(
            session_id="s_test",
            status="ended",
            primary_thread="auth",
            mounted_threads=["auth", "memory"],
            touched_threads=["auth"],
            turn_count=5,
            last_event_seq=47,
        )
        raw = m.model_dump_json()
        restored = SessionManifest.model_validate_json(raw)
        assert restored.session_id == "s_test"
        assert restored.status == "ended"
        assert restored.mounted_threads == ["auth", "memory"]


# ---------------------------------------------------------------------------
# SessionRuntimeState
# ---------------------------------------------------------------------------


class TestSessionRuntimeState:
    def test_convenience_proxies(self) -> None:
        pub = SessionEventPublisher("s_test")
        manifest = SessionManifest(
            session_id="s_test",
            primary_thread="auth",
            mounted_threads=["auth", "memory"],
        )
        from datetime import datetime

        state = SessionRuntimeState(
            manifest=manifest,
            last_activity_at=datetime.now(),
            event_publisher=pub,
        )
        assert state.session_id == "s_test"
        assert state.primary_thread == "auth"
        assert state.mounted_threads == {"auth", "memory"}

    def test_touch_thread(self) -> None:
        pub = SessionEventPublisher("s_test")
        manifest = SessionManifest(session_id="s_test")
        from datetime import datetime

        state = SessionRuntimeState(
            manifest=manifest,
            last_activity_at=datetime.now(),
            event_publisher=pub,
        )
        state.touch_thread("auth")
        state.touch_thread("memory")
        state.touch_thread("auth")  # duplicate — no-op
        assert state.touched_threads == {"auth", "memory"}
        # sorted in manifest for deterministic JSON
        assert state.manifest.touched_threads == ["auth", "memory"]

    def test_mount_unmount_thread(self) -> None:
        pub = SessionEventPublisher("s_test")
        manifest = SessionManifest(session_id="s_test")
        from datetime import datetime

        state = SessionRuntimeState(
            manifest=manifest,
            last_activity_at=datetime.now(),
            event_publisher=pub,
        )
        state.mount_thread("auth")
        state.mount_thread("memory")
        assert state.mounted_threads == {"auth", "memory"}

        state.unmount_thread("auth")
        assert state.mounted_threads == {"memory"}

    def test_set_primary_thread_auto_mounts(self) -> None:
        pub = SessionEventPublisher("s_test")
        manifest = SessionManifest(session_id="s_test")
        from datetime import datetime

        state = SessionRuntimeState(
            manifest=manifest,
            last_activity_at=datetime.now(),
            event_publisher=pub,
        )
        state.set_primary_thread("auth")
        assert state.primary_thread == "auth"
        assert "auth" in state.mounted_threads


# ---------------------------------------------------------------------------
# Identity helpers
# ---------------------------------------------------------------------------


class TestIdentityHelpers:
    def test_session_id_format(self) -> None:
        sid = build_session_id()
        assert sid.startswith("s_")
        parts = sid.split("_")
        assert len(parts) == 3
        assert len(parts[1]) == 14  # YYYYMMDDHHmmss
        assert len(parts[2]) == 8  # hex

    def test_session_id_uniqueness(self) -> None:
        ids = {build_session_id() for _ in range(100)}
        assert len(ids) == 100

    def test_turn_id_format(self) -> None:
        assert build_turn_id(0) == "t_0000"
        assert build_turn_id(1) == "t_0001"
        assert build_turn_id(9999) == "t_9999"


# ---------------------------------------------------------------------------
# SessionEventPublisher
# ---------------------------------------------------------------------------


class _CollectorSink(SessionEventSink):
    def __init__(self) -> None:
        self.events: list[SessionEvent] = []

    async def on_event(self, event: SessionEvent) -> None:
        self.events.append(event)


class _FailingSink(SessionEventSink):
    async def on_event(self, event: SessionEvent) -> None:
        raise RuntimeError("sink failure")


class TestSessionEventPublisher:
    @pytest.mark.asyncio
    async def test_seq_monotonic(self) -> None:
        pub = SessionEventPublisher("s_test")
        e1 = await pub.emit(SESSION_CREATED, actor="engine")
        e2 = await pub.emit(TURN_STARTED, actor="engine")
        assert e1.seq == 1
        assert e2.seq == 2
        assert pub.last_seq == 2

    @pytest.mark.asyncio
    async def test_fan_out_to_sinks(self) -> None:
        pub = SessionEventPublisher("s_test")
        sink_a = _CollectorSink()
        sink_b = _CollectorSink()
        pub.add_sink(sink_a)
        pub.add_sink(sink_b)

        await pub.emit(SESSION_CREATED, actor="engine")
        assert len(sink_a.events) == 1
        assert len(sink_b.events) == 1
        assert sink_a.events[0].seq == sink_b.events[0].seq

    @pytest.mark.asyncio
    async def test_failing_sink_does_not_block(self) -> None:
        pub = SessionEventPublisher("s_test")
        good = _CollectorSink()
        pub.add_sink(_FailingSink())
        pub.add_sink(good)

        await pub.emit(SESSION_CREATED, actor="engine")
        assert len(good.events) == 1  # good sink still receives event

    @pytest.mark.asyncio
    async def test_remove_sink(self) -> None:
        pub = SessionEventPublisher("s_test")
        sink = _CollectorSink()
        pub.add_sink(sink)
        pub.remove_sink(sink)

        await pub.emit(SESSION_CREATED, actor="engine")
        assert len(sink.events) == 0

    @pytest.mark.asyncio
    async def test_close_detaches_all(self) -> None:
        pub = SessionEventPublisher("s_test")
        sink = _CollectorSink()
        pub.add_sink(sink)
        await pub.close()

        await pub.emit(SESSION_CREATED, actor="engine")
        assert len(sink.events) == 0

    @pytest.mark.asyncio
    async def test_initial_seq(self) -> None:
        pub = SessionEventPublisher("s_test", initial_seq=100)
        e = await pub.emit(SESSION_CREATED, actor="engine")
        assert e.seq == 101
