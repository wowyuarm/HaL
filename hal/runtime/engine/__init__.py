"""AgentEngine — unified execution engine."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from hal.bus.queue import MessageBus
from hal.context.builder import ContextBuilder
from hal.context.compiler import ContextCompiler
from hal.context.message_building import add_assistant_message, add_tool_result
from hal.context.metrics import MetricsCollector
from hal.context.thread_mentions import detect_thread_mentions
from hal.domain.event_sink import SessionEventPublisher, SessionEventSink
from hal.domain.events import SESSION_ENDED, is_durable
from hal.domain.ports import LLMProviderPort
from hal.domain.session import SessionManifest, SessionRuntimeState, build_session_id
from hal.memory.manager import MemoryManager
from hal.runtime.brief import run_session_brief
from hal.runtime.session import (
    build_session_snapshot_messages,
    generate_session_checkpoint,
    maybe_compact_session_history,
    tick_session_lifecycle,
)
from hal.runtime.subagent import SubagentManager
from hal.runtime.tool_factory import create_tools
from hal.workspace import MetricsRepository, SessionStore, ThreadRepository, WorkspaceLayout

from .background_resume import _EngineBackgroundResume
from .inspect import build_context_inspection
from .processing import (
    build_direct_inbound_message,
    build_engine_error_response,
    execute_loop,
    process_message,
)
from .subagent_injection import (
    ParsedSubagentResult,
    _build_subagent_injection,
    _split_subagent_tool_result,
)
from .subscribers import _EngineBackgroundSubscribers

if TYPE_CHECKING:
    from hal.bus.events import SubagentCompleteEvent
    from hal.context.metrics import ContextMetrics
    from hal.infra.config.schema import (
        ChannelsConfig,
        EngineConfig,
        ExecToolConfig,
        HistoryConfig,
        WebFetchConfig,
        WebSearchConfig,
    )
    from hal.memory.search import MemorySearch


PROCESSING_MODE = "default"


# ---------------------------------------------------------------------------
# Durable event sink — writes to per-session working-log.jsonl
# ---------------------------------------------------------------------------


class _WorkingLogSink(SessionEventSink):
    """Sink that persists durable events to the session store."""

    def __init__(self, store: SessionStore, manifest: SessionManifest) -> None:
        self._store = store
        self._manifest = manifest

    async def on_event(self, event: object) -> None:
        from hal.domain.events import SessionEvent

        if not isinstance(event, SessionEvent):
            return
        if not is_durable(event.type):
            return
        self._store.append_event(self._manifest.session_id, event)
        self._manifest.last_event_seq = event.seq
        self._store.write_manifest(self._manifest.session_id, self._manifest)


class AgentEngine:
    """Unified execution engine for user conversations."""

    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProviderPort,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 20,
        web_search_api_key: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
        restrict_to_workspace: bool = False,
        memory_manager: MemoryManager | None = None,
        worker_model: str = "default",
        worker_provider: LLMProviderPort | None = None,
        memory_search: "MemorySearch | None" = None,
        auto_inject_top_k: int = 3,
        recall_min_score: float = 0.0,
        history_config: "HistoryConfig | None" = None,
        engine_config: "EngineConfig | None" = None,
        web_search_config: "WebSearchConfig | None" = None,
        web_fetch_config: "WebFetchConfig | None" = None,
        channels_config: "ChannelsConfig | None" = None,
    ):
        from hal.infra.config.schema import EngineConfig, ExecToolConfig, HistoryConfig

        self.bus = bus
        self.provider = provider
        self.workspace = workspace
        self.thread_repository = ThreadRepository(workspace)
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.web_search_api_key = web_search_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.restrict_to_workspace = restrict_to_workspace
        self._memory_search = memory_search
        self._auto_inject_top_k = auto_inject_top_k
        self._recall_min_score = recall_min_score
        self._history_config = history_config or HistoryConfig()
        self._engine_config = engine_config or EngineConfig()
        self._web_search_config = web_search_config
        self._web_fetch_config = web_fetch_config
        self._channels_config = channels_config
        self._metrics_repository = MetricsRepository(workspace)
        self._metrics_collector = MetricsCollector(self._metrics_repository.context_metrics_path())
        self._background_resume = _EngineBackgroundResume(engine=self)
        self._layout = WorkspaceLayout(workspace)
        self._session_store = SessionStore(self._layout)
        self._sessions: dict[str, SessionRuntimeState] = {}
        # Transport route mapping: session_key (channel:chat_id) → session_id
        self._session_routes: dict[str, str] = {}
        # Reverse mapping: session_id → (channel, chat_id)
        self._session_channels: dict[str, tuple[str, str]] = {}

        self.memory = memory_manager or MemoryManager(workspace)
        self.context = ContextBuilder(
            workspace,
            memory_manager=self.memory,
            max_thread_registry_size=self._history_config.max_thread_registry_size,
            baseline_max_active_threads=self._history_config.baseline_max_active_threads,
            baseline_active_threads_max_total_tokens=(
                self._history_config.baseline_active_threads_max_total_tokens
            ),
            baseline_active_thread_max_tokens=self._history_config.baseline_active_thread_max_tokens,
            related_thread_hops=self._history_config.related_thread_hops,
        )
        self.context_registry = self.context.registry
        self.context_compiler = ContextCompiler(
            context_builder=self.context,
            context_registry=self.context_registry,
            memory_search=self._memory_search,
            auto_inject_top_k=self._auto_inject_top_k,
            recall_min_score=self._recall_min_score,
        )

        sa_provider = worker_provider or provider
        sa_model = self.model if worker_model == "default" else worker_model
        self._worker_provider = sa_provider
        self._worker_model = sa_model
        self.subagents = SubagentManager(
            provider=sa_provider,
            workspace=workspace,
            model=sa_model,
            web_search_api_key=web_search_api_key,
            exec_config=self.exec_config,
            restrict_to_workspace=restrict_to_workspace,
            max_iterations=max_iterations,
            web_search_config=web_search_config,
            web_fetch_config=web_fetch_config,
            bus=self.bus,
        )
        self._background_subscribers = _EngineBackgroundSubscribers(engine=self)

        self._running = False
        self._register_default_tools()
        self._restore_active_sessions()

    def _register_default_tools(self) -> None:
        """Register the default set of tools via the shared factory."""
        self.tools = create_tools(
            workspace=self.workspace,
            exec_config=self.exec_config,
            restrict_to_workspace=self.restrict_to_workspace,
            web_search_api_key=self.web_search_api_key,
            web_search_config=self._web_search_config,
            web_fetch_config=self._web_fetch_config,
            bus=self.bus,
            subagent_manager=self.subagents,
            memory_search=self._memory_search,
        )

    def disable_memory_search(self) -> None:
        """Disable memory search integration and unregister recall tool."""
        self._memory_search = None
        self.context_compiler.set_memory_search(None)
        self.tools.unregister("recall")

    async def run(self) -> None:
        """Run the engine, processing messages from the bus."""
        self._running = True
        logger.info("Agent engine started")

        while self._running:
            try:
                msg = await asyncio.wait_for(
                    self.bus.consume_inbound(),
                    timeout=self._engine_config.inbound_poll_timeout_s,
                )
                try:
                    # Error policy:
                    # - per-message failures are logged and converted into a user-facing fallback
                    # - the engine loop remains alive for subsequent messages
                    response = await self._dispatch(msg)
                    if response:
                        await self.bus.publish_outbound(response)
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    await self.bus.publish_outbound(build_engine_error_response(msg=msg, error=e))
            except asyncio.TimeoutError:
                await self._tick_session_lifecycle()
                continue

    def stop(self) -> None:
        """Stop the engine."""
        self._running = False
        self._background_subscribers.close()
        self._background_resume.close()
        logger.info("Agent engine stopping")

    async def _dispatch(self, msg: object) -> object | None:
        """Route a message to the main processing path."""
        return await self.process(msg)

    async def process(self, msg: object) -> object | None:
        """Process a user message end-to-end."""
        return await process_message(self, msg, PROCESSING_MODE)

    def _drain_pending_for_session(self, session_key: str) -> list[object]:
        """Drain inbound queue messages for the target session without blocking."""
        matching: list[object] = []
        others: list[object] = []

        while not self.bus.inbound.empty():
            try:
                msg = self.bus.inbound.get_nowait()
            except asyncio.QueueEmpty:
                break
            if msg.session_key == session_key:
                matching.append(msg)
            else:
                others.append(msg)

        for msg in others:
            self.bus.inbound.put_nowait(msg)

        return matching

    # -- session lifecycle (session_id-first) --------------------------------

    def create_session(
        self,
        *,
        channel: str,
        chat_id: str,
        primary_thread: str | None = None,
        mounted_threads: set[str] | None = None,
    ) -> SessionRuntimeState:
        """Create a new session and register it with the engine."""
        sid = build_session_id()
        effective_mounted = sorted(mounted_threads or ([primary_thread] if primary_thread else []))
        manifest = SessionManifest(
            session_id=sid,
            primary_thread=primary_thread,
            mounted_threads=effective_mounted,
            channel=channel,
            chat_id=chat_id,
        )
        publisher = SessionEventPublisher(sid)
        publisher.add_sink(_WorkingLogSink(self._session_store, manifest))
        state = SessionRuntimeState(
            manifest=manifest,
            last_activity_at=datetime.now(),
            event_publisher=publisher,
        )
        self._session_store.create(sid)
        self._session_store.write_manifest(sid, manifest)
        self._sessions[sid] = state
        self._register_session_route(session_id=sid, channel=channel, chat_id=chat_id)
        return state

    def resume_session(self, session_id: str) -> SessionRuntimeState | None:
        """Resume a session from in-memory cache or durable manifest."""
        state = self._sessions.get(session_id)
        if state is not None:
            return state
        manifest = self._session_store.read_manifest(session_id)
        if manifest is None:
            return None
        publisher = SessionEventPublisher(session_id, initial_seq=manifest.last_event_seq)
        publisher.add_sink(_WorkingLogSink(self._session_store, manifest))
        state = SessionRuntimeState(
            manifest=manifest,
            last_activity_at=datetime.now(),
            event_publisher=publisher,
        )
        self._sessions[session_id] = state
        return state

    async def end_session(
        self,
        session_id: str,
        *,
        status: str = "ended",
        reason: str | None = None,
    ) -> None:
        """End a session, emit closing event, and clean up."""
        state = self._sessions.get(session_id)
        if state is None:
            return
        state.manifest.status = status
        state.manifest.ended_at = datetime.now().isoformat()
        await state.event_publisher.emit(
            SESSION_ENDED,
            actor="engine",
            payload={"reason": reason or status},
        )
        self._session_store.write_manifest(session_id, state.manifest)
        await state.event_publisher.close()
        self._sessions.pop(session_id, None)
        self._session_channels.pop(session_id, None)
        for key, value in list(self._session_routes.items()):
            if value == session_id:
                self._session_routes.pop(key, None)

    def _register_session_route(self, *, session_id: str, channel: str, chat_id: str) -> None:
        """Map a transport session_key to an engine session_id."""
        session_key = f"{channel}:{chat_id}"
        self._session_routes[session_key] = session_id
        self._session_channels[session_id] = (channel, chat_id)

    def _get_session_route(self, session_id: str) -> tuple[str, str] | None:
        """Return (channel, chat_id) for a session, or None."""
        return self._session_channels.get(session_id)

    def _ensure_session_for_inbound(self, msg: object) -> SessionRuntimeState:
        """Get or create a session for an inbound message (transport adapter path)."""
        session_key = msg.session_key
        session_id = self._session_routes.get(session_key)
        if session_id:
            state = self._sessions.get(session_id)
            if state is not None:
                # Clean up completed brief tasks
                if state.brief_task is not None and state.brief_task.done():
                    self._sessions.pop(session_id, None)
                    self._session_routes.pop(session_key, None)
                else:
                    return state

        state = self.create_session(channel=msg.channel, chat_id=msg.chat_id)
        return state

    # -- session state accessors (session_id-based) --------------------------

    def _touch_session(self, session_id: str) -> None:
        """Refresh last-activity timestamp."""
        state = self._sessions.get(session_id)
        if state is not None:
            state.last_activity_at = datetime.now()

    def _mark_threads_touched(self, session_id: str, thread_slugs: set[str]) -> None:
        """Mark threads touched in the runtime session."""
        if not thread_slugs:
            return
        state = self._sessions.get(session_id)
        if state is None:
            return
        for slug in thread_slugs:
            state.touch_thread(slug)

    def _detect_thread_mentions(self, text: str) -> set[str]:
        """Best-effort thread mention detection from user-visible text."""
        return detect_thread_mentions(text, self.context_registry.thread_snapshot())

    def _filter_new_context_hint_keys(self, session_id: str, keys: list[str]) -> set[str]:
        """Return keys not yet suggested in the session and mark them as seen."""
        state = self._sessions.get(session_id)
        if state is None:
            return set()
        new_keys = {key for key in keys if key not in state.context_hint_keys}
        state.context_hint_keys.update(new_keys)
        return new_keys

    async def _tick_session_lifecycle(self) -> None:
        """Clean up finished brief tasks after explicit session closure."""
        await tick_session_lifecycle(self)

    async def _start_session_brief(self, session_id: str, *, user_prompt: str = "") -> None:
        """Start background brief worker task for one session."""
        state = self._sessions.get(session_id)
        if state is None:
            return
        if state.brief_task is not None:
            return
        state.brief_task = asyncio.create_task(
            self._run_session_brief(session_id, user_prompt=user_prompt)
        )

    async def _run_session_brief(self, session_id: str, *, user_prompt: str = "") -> None:
        """Run brief worker agent for one closed session."""
        await run_session_brief(self, session_id, user_prompt=user_prompt)

    async def _maybe_compact_session_history(
        self,
        *,
        session_id: str,
        history: list[dict[str, object]],
        token_model: str | None,
    ) -> list[dict[str, object]]:
        """Compact older session turns when in-memory history exceeds token budget."""
        return await maybe_compact_session_history(
            self,
            session_id=session_id,
            history=history,
            token_model=token_model,
        )

    async def _generate_session_checkpoint(
        self,
        compactable_messages: list[dict[str, object]],
        *,
        token_model: str | None,
    ) -> str:
        """Generate one compaction checkpoint for a slice of older messages."""
        return await generate_session_checkpoint(
            self,
            compactable_messages=compactable_messages,
            token_model=token_model,
        )

    def _get_session_history(self, session_id: str) -> list[dict[str, object]]:
        """Return full in-memory history for the active runtime session."""
        state = self._sessions.get(session_id)
        if state is None:
            return []
        return list(state.replay_history)

    def _set_session_history(self, session_id: str, history: list[dict[str, object]]) -> None:
        """Replace in-memory history snapshot for the active session."""
        state = self._sessions.get(session_id)
        if state is None:
            return
        state.replay_history = list(history)

    def _build_session_snapshot_messages(
        self,
        *,
        session_id: str,
        token_model: str | None = None,
    ) -> list[dict[str, object]]:
        """Build a clean session snapshot from system prompt and in-memory history."""
        return build_session_snapshot_messages(
            self,
            session_id=session_id,
            token_model=token_model,
        )

    async def _execute_loop(
        self,
        messages: list[dict[str, object]],
        max_iterations: int,
        session_id: str | None = None,
    ) -> tuple[str | None, object, list[object]]:
        """Run the LLM tool-calling loop via the shared runtime."""
        # Resolve channel/chat_id from session route for hook compat
        channel: str | None = None
        chat_id: str | None = None
        session_key: str | None = None
        if session_id:
            route = self._get_session_route(session_id)
            if route:
                channel, chat_id = route
                session_key = f"{channel}:{chat_id}"
        return await execute_loop(
            self,
            messages=messages,
            max_iterations=max_iterations,
            add_assistant_message_fn=add_assistant_message,
            add_tool_result_fn=add_tool_result,
            session_key=session_key,
            channel=channel,
            chat_id=chat_id,
        )

    def _update_tool_contexts(self, channel: str, chat_id: str) -> None:
        """Update context-dependent tools with current channel/chat info."""
        self.tools.update_context(channel, chat_id)

    def _get_channel_progress_policy(self, channel: str | None) -> tuple[bool, bool]:
        """Return (send_progress, send_tool_hints) for a channel."""
        if not channel or not self._channels_config:
            return True, True

        channel_config = getattr(self._channels_config, channel, None)
        if channel_config is None:
            return True, True

        send_progress = bool(getattr(channel_config, "send_progress", True))
        send_tool_hints = bool(getattr(channel_config, "send_tool_hints", True))
        return send_progress, send_tool_hints

    def _record_metrics(self, metrics: "ContextMetrics") -> None:
        """Best-effort metrics recording without affecting user flows."""
        try:
            self._metrics_collector.record(metrics)
        except Exception as e:
            logger.warning(f"Failed to record context metrics: {e}")

    def _set_session_active(self, session_id: str, active: bool) -> None:
        """Track whether a session currently has an active engine loop."""
        self._background_resume.set_session_active(session_id, active)

    def _store_session_snapshot(
        self,
        *,
        session_id: str,
        messages: list[dict[str, object]],
        final_content: str | None,
    ) -> None:
        """Store full loop context snapshot for potential background continuation."""
        route = self._get_session_route(session_id)
        channel, chat_id = route if route else ("unknown", "unknown")
        self._background_resume.store_session_snapshot(
            session_id=session_id,
            channel=channel,
            chat_id=chat_id,
            messages=messages,
            final_content=final_content,
        )

    def _clear_session_snapshot(self, session_id: str) -> None:
        """Delete persisted/cached background-resume snapshot."""
        self._background_resume.clear_session_snapshot(session_id)

    def _restore_active_sessions(self) -> None:
        """Restore active/briefing sessions from durable manifests.

        Active sessions are restored first so their transport routes take
        precedence over stale briefing sessions sharing the same channel:chat_id.
        """
        for status in ("active", "briefing"):
            for manifest in self._session_store.list_sessions(status=status):
                self.resume_session(manifest.session_id)
                if manifest.channel and manifest.chat_id:
                    session_key = f"{manifest.channel}:{manifest.chat_id}"
                    if session_key not in self._session_routes:
                        self._register_session_route(
                            session_id=manifest.session_id,
                            channel=manifest.channel,
                            chat_id=manifest.chat_id,
                        )

    async def queue_background_completion(self, event: "SubagentCompleteEvent") -> None:
        """Queue detached subagent completions and continue same-session loop when idle."""
        await self._background_resume.queue_background_completion(event)

    async def inspect_context(
        self,
        *,
        session_id: str | None = None,
        channel: str = "unknown",
        chat_id: str = "unknown",
        current_message: str,
    ) -> dict[str, object]:
        """Build the current context and return debug-friendly metadata."""
        mounted: set[str] | None = None
        history: list[dict[str, object]] = []
        if session_id:
            state = self._sessions.get(session_id)
            if state:
                mounted = state.mounted_threads
                history = list(state.replay_history)
                route = self._get_session_route(session_id)
                if route:
                    channel, chat_id = route

        return await build_context_inspection(
            provider=self.provider,
            model=self.model,
            memory=self.memory,
            context_builder=self.context,
            context_registry=self.context_registry,
            tools_registry=self.tools,
            memory_search=self._memory_search,
            auto_inject_top_k=self._auto_inject_top_k,
            recall_min_score=self._recall_min_score,
            history_config=self._history_config,
            channel=channel,
            chat_id=chat_id,
            session_id=session_id,
            session_history=history,
            mounted_threads=mounted,
            current_message=current_message,
            mode=PROCESSING_MODE,
        )

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
    ) -> str:
        """Process a message directly for CLI usage."""
        # Auto-create/reuse session for CLI path
        session_id = self._session_routes.get(session_key)
        if not session_id:
            state = self.create_session(channel=channel, chat_id=chat_id)
            session_id = state.session_id
        msg = build_direct_inbound_message(
            channel=channel, chat_id=chat_id, content=content, session_id=session_id
        )
        response = await self.process(msg)
        return str(getattr(response, "content", "")) if response else ""


def __getattr__(name: str) -> object:
    """Lazily expose compatibility exports without hard runtime coupling."""
    if name == "LoopMetadata":
        from hal.runtime.loop import LoopMetadata as _LoopMetadata

        return _LoopMetadata
    raise AttributeError(name)


__all__ = [
    "AgentEngine",
    "LoopMetadata",
    "ParsedSubagentResult",
    "PROCESSING_MODE",
    "_build_subagent_injection",
    "_split_subagent_tool_result",
]
