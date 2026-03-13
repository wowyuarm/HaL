"""Bridge native web requests directly onto the session-first engine."""

from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from hal.domain.event_sink import SessionEventSink
from hal.domain.events import SessionEvent
from hal.domain.session import SessionManifest
from hal.runtime.engine.processing import build_direct_inbound_message
from hal.workspace.layout import WorkspaceLayout
from hal.workspace.session_store import SessionStore
from hal.workspace.threads import ThreadRegistryEntry, ThreadRepository

_THREAD_LIST_MAX = 200
_WEB_CHANNEL = "web"
_WEB_SENDER_ID = "web-user"


class _QueueSink(SessionEventSink):
    """Fan out live session events into an asyncio queue."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[SessionEvent] = asyncio.Queue()

    async def on_event(self, event: SessionEvent) -> None:
        await self.queue.put(event)


@dataclass(slots=True)
class SessionSubscription:
    """A live event subscription attached to one active session."""

    session_id: str
    queue: asyncio.Queue[SessionEvent]
    _close: Any

    async def next_event(self) -> SessionEvent:
        """Wait for and return the next live session event."""
        return await self.queue.get()

    async def close(self) -> None:
        """Detach the subscription from the underlying event publisher."""
        await self._close()


class SessionBridge:
    """Session-oriented facade used by the native web server."""

    def __init__(self, engine: Any) -> None:
        self._engine = engine
        self._layout = WorkspaceLayout(engine.workspace)
        self._session_store = SessionStore(self._layout)
        self._threads = ThreadRepository(engine.workspace)

    async def create_session(
        self,
        *,
        primary_thread: str | None = None,
        mounted_threads: list[str] | None = None,
    ) -> SessionManifest:
        """Create a new session rooted in the chosen thread scope."""
        effective = {slug for slug in (mounted_threads or []) if slug}
        if primary_thread:
            effective.add(primary_thread)
        self._validate_threads(effective)

        state = self._engine.create_session(
            primary_thread=primary_thread,
            mounted_threads=effective or None,
        )
        await self._engine.emit_session_created(state.session_id)
        return state.manifest

    def list_sessions(
        self,
        *,
        thread_slug: str | None = None,
        status: str | None = None,
    ) -> list[SessionManifest]:
        """Return persisted sessions, newest first."""
        sessions = self._session_store.list_sessions(thread_slug=thread_slug, status=status)
        return list(reversed(sessions))

    def get_session(self, session_id: str) -> SessionManifest | None:
        """Return one session manifest when present."""
        return self._session_store.read_manifest(session_id)

    def get_events(self, session_id: str, *, after_seq: int = 0) -> list[SessionEvent]:
        """Return durable working-log events for one session."""
        return self._session_store.read_events(session_id, after_seq=after_seq)

    async def submit_turn(self, session_id: str, content: str) -> str | None:
        """Submit one user turn into an existing active session."""
        manifest = self._require_session(session_id)
        if manifest.status != "active":
            raise ValueError(f"Session {session_id} is not active (status={manifest.status})")

        msg = build_direct_inbound_message(
            channel=_WEB_CHANNEL,
            chat_id=session_id,
            content=content,
            session_id=session_id,
        )
        msg.sender_id = _WEB_SENDER_ID
        response = await self._engine.process(msg)
        return str(getattr(response, "content", "")) if response else None

    async def end_session(
        self,
        session_id: str,
        *,
        reason: str,
        user_prompt: str = "",
    ) -> str | None:
        """End one session via the existing human-in-the-loop control commands."""
        if reason == "brief":
            command = f"/brief {user_prompt}".strip()
            return await self.submit_turn(session_id, command)
        if reason == "drop":
            return await self.submit_turn(session_id, "/drop")
        raise ValueError(f"Unsupported session end reason: {reason}")

    async def update_scope(
        self,
        session_id: str,
        *,
        add_threads: list[str] | None = None,
        remove_threads: list[str] | None = None,
    ) -> SessionManifest:
        """Mutate mounted thread scope for one active session."""
        add = {slug for slug in (add_threads or []) if slug}
        remove = {slug for slug in (remove_threads or []) if slug}
        self._validate_threads(add | remove)
        return await self._engine.update_session_scope(
            session_id,
            add_threads=add or None,
            remove_threads=remove or None,
        )

    async def subscribe(self, session_id: str) -> SessionSubscription:
        """Attach a live event subscriber to an active in-memory session."""
        self._require_session(session_id)
        sink = _QueueSink()
        state = self._engine.resume_session(session_id)
        if state is not None and state.manifest.status in {"active", "briefing"}:
            state.event_publisher.add_sink(sink)

        async def _close() -> None:
            state = self._engine._sessions.get(session_id)
            if state is not None:
                state.event_publisher.remove_sink(sink)

        return SessionSubscription(session_id=session_id, queue=sink.queue, _close=_close)

    def list_threads(self) -> list[dict[str, Any]]:
        """Return thread summaries enriched with session counts."""
        entries = self._threads.collect_registry_entries(max_entries=_THREAD_LIST_MAX)
        counts = self._build_thread_session_counts()
        return [
            {
                "slug": entry.slug,
                "name": entry.name,
                "status": entry.status,
                "scope": entry.scope,
                "description": entry.description,
                "updated_at": entry.updated_at,
                "session_counts": dict(counts.get(entry.slug, Counter())),
            }
            for entry in entries
        ]

    def get_thread(self, slug: str) -> dict[str, Any]:
        """Return thread detail, BRIEF.md, and associated sessions."""
        entry = self._require_thread_entry(slug)
        brief = self._threads.read_state(slug) or ""
        sessions = self.list_sessions(thread_slug=slug)
        counts = Counter(session.status for session in sessions)
        return {
            "slug": entry.slug,
            "name": entry.name,
            "status": entry.status,
            "scope": entry.scope,
            "description": entry.description,
            "updated_at": entry.updated_at,
            "brief_markdown": brief,
            "session_counts": dict(counts),
            "sessions": [session.model_dump(mode="json") for session in sessions],
        }

    def _build_thread_session_counts(self) -> dict[str, Counter[str]]:
        counts: dict[str, Counter[str]] = defaultdict(Counter)
        for manifest in self._session_store.list_sessions():
            slugs = set(manifest.mounted_threads)
            if manifest.primary_thread:
                slugs.add(manifest.primary_thread)
            slugs.update(manifest.touched_threads)
            for slug in slugs:
                counts[slug][manifest.status] += 1
        return counts

    def _require_session(self, session_id: str) -> SessionManifest:
        manifest = self.get_session(session_id)
        if manifest is None:
            raise ValueError(f"Unknown session_id: {session_id}")
        return manifest

    def _require_thread_entry(self, slug: str) -> ThreadRegistryEntry:
        for entry in self._threads.collect_registry_entries(max_entries=_THREAD_LIST_MAX):
            if entry.slug == slug:
                return entry
        raise ValueError(f"Unknown thread slug: {slug}")

    def _validate_threads(self, slugs: set[str]) -> None:
        if not slugs:
            return
        available = {
            entry.slug
            for entry in self._threads.collect_registry_entries(max_entries=_THREAD_LIST_MAX)
        }
        missing = sorted(slug for slug in slugs if slug not in available)
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"Unknown thread slug(s): {joined}")
