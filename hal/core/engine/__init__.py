"""AgentEngine — unified execution engine."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from hal.bus.queue import MessageBus
from hal.core.context.builder import ContextBuilder
from hal.core.context.metrics import MetricsCollector
from hal.core.memory.manager import MemoryManager
from hal.core.ports import LLMProviderPort
from hal.core.runtime.loop import run_tool_loop
from hal.core.runtime.summary import generate_summary
from hal.core.runtime.tool_factory import create_tools
from hal.core.subagent import SubagentManager

from .background_resume import _EngineBackgroundResume
from .hooks import _EngineLoopHooks
from .inspect import build_context_inspection
from .processing import build_direct_inbound_message, build_engine_error_response, process_message
from .subagent_injection import (
    ParsedSubagentResult,
    _build_subagent_injection,
    _split_subagent_tool_result,
)
from .subscribers import _EngineBackgroundSubscribers

if TYPE_CHECKING:
    from hal.bus.events import SubagentCompleteEvent
    from hal.core.context.metrics import ContextMetrics
    from hal.core.memory.search import MemorySearch
    from hal.infra.config.schema import (
        ChannelsConfig,
        EngineConfig,
        ExecToolConfig,
        HistoryConfig,
        WebFetchConfig,
        WebSearchConfig,
    )


PROCESSING_MODE = "default"


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
        summary_model: str = "default",
        summary_provider: LLMProviderPort | None = None,
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
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.web_search_api_key = web_search_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.restrict_to_workspace = restrict_to_workspace
        self._summary_model = summary_model
        self._summary_provider = summary_provider
        self._memory_search = memory_search
        self._auto_inject_top_k = auto_inject_top_k
        self._recall_min_score = recall_min_score
        self._history_config = history_config or HistoryConfig()
        self._engine_config = engine_config or EngineConfig()
        self._web_search_config = web_search_config
        self._web_fetch_config = web_fetch_config
        self._channels_config = channels_config
        self._pending_summaries: dict[str, asyncio.Task] = {}
        self._metrics_collector = MetricsCollector(workspace / "logs" / "context_metrics.jsonl")
        self._background_resume = _EngineBackgroundResume(engine=self)

        self.memory = memory_manager or MemoryManager(workspace)
        self.context = ContextBuilder(workspace, memory_manager=self.memory)

        sa_provider = worker_provider or provider
        sa_model = self.model if worker_model == "default" else worker_model
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

    async def _execute_loop(
        self,
        messages: list[dict[str, object]],
        max_iterations: int,
        session_key: str | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
    ) -> tuple[str | None, object, list[object]]:
        """Run the LLM tool-calling loop via the shared runtime."""
        hooks = _EngineLoopHooks(
            engine=self,
            session_key=session_key,
            channel=channel,
            chat_id=chat_id,
        )
        try:
            final_content, meta = await run_tool_loop(
                provider=self.provider,
                model=self.model,
                tools=self.tools,
                messages=messages,
                max_iterations=max_iterations,
                hooks=hooks,
                add_assistant_message=self.context.add_assistant_message,
                add_tool_result=self.context.add_tool_result,
                llm_retry_attempts=self._engine_config.llm_retry_attempts,
                llm_retry_base_delay_s=self._engine_config.llm_retry_base_delay_s,
                llm_retry_max_delay_s=self._engine_config.llm_retry_max_delay_s,
            )
            return final_content, meta, hooks.injected
        finally:
            hooks.close()

    def _summary_model_id(self) -> str:
        """Resolve the model to use for summary generation."""
        return self.model if self._summary_model == "default" else self._summary_model

    def _trigger_summary(
        self, meta: object, final_content: str, channel: str, chat_id: str
    ) -> asyncio.Task | None:
        """Create an async summary task if the loop qualifies."""
        if not bool(getattr(meta, "needs_summary", False)):
            return None
        return asyncio.create_task(
            generate_summary(
                meta=meta,
                final_content=final_content,
                channel=channel,
                chat_id=chat_id,
                provider=self._summary_provider or self.provider,
                model=self._summary_model_id(),
                memory=self.memory,
            )
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

    def _set_session_active(self, session_key: str, active: bool) -> None:
        """Track whether a session currently has an active engine loop."""
        self._background_resume.set_session_active(session_key, active)

    def _store_session_snapshot(
        self,
        *,
        session_key: str,
        channel: str,
        chat_id: str,
        messages: list[dict[str, object]],
        final_content: str | None,
    ) -> None:
        """Store full loop context snapshot for potential background continuation."""
        self._background_resume.store_session_snapshot(
            session_key=session_key,
            channel=channel,
            chat_id=chat_id,
            messages=messages,
            final_content=final_content,
        )

    async def queue_background_completion(self, event: "SubagentCompleteEvent") -> None:
        """Queue detached subagent completions and continue same-session loop when idle."""
        await self._background_resume.queue_background_completion(event)

    async def inspect_context(
        self,
        *,
        channel: str,
        chat_id: str,
        current_message: str,
    ) -> dict[str, object]:
        """Build the current context and return debug-friendly metadata."""
        return await build_context_inspection(
            provider=self.provider,
            model=self.model,
            memory=self.memory,
            context_builder=self.context,
            tools_registry=self.tools,
            memory_search=self._memory_search,
            auto_inject_top_k=self._auto_inject_top_k,
            recall_min_score=self._recall_min_score,
            history_config=self._history_config,
            channel=channel,
            chat_id=chat_id,
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
        msg = build_direct_inbound_message(channel=channel, chat_id=chat_id, content=content)
        response = await self.process(msg)
        return str(getattr(response, "content", "")) if response else ""


# Backward compatibility alias
AgentLoop = AgentEngine


def __getattr__(name: str) -> object:
    """Lazily expose compatibility exports without hard runtime coupling."""
    if name == "LoopMetadata":
        from hal.core.runtime.loop import LoopMetadata as _LoopMetadata

        return _LoopMetadata
    raise AttributeError(name)


__all__ = [
    "AgentEngine",
    "AgentLoop",
    "LoopMetadata",
    "ParsedSubagentResult",
    "PROCESSING_MODE",
    "_build_subagent_injection",
    "_split_subagent_tool_result",
]
