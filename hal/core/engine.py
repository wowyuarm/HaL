"""AgentEngine — unified execution engine for all interaction modes."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from hal.bus.events import InboundMessage, OutboundMessage
from hal.bus.queue import MessageBus
from hal.capabilities.tools.message import MessageTool
from hal.capabilities.tools.schedule import CronTool
from hal.capabilities.tools.spawn import SpawnTool
from hal.core.context.builder import ContextBuilder, ExecutionMode
from hal.core.context.metrics import ContextMetrics, MetricsCollector
from hal.core.context.token_budget import (
    rough_tokens_from_chars,
    trim_text_to_token_budget,
)
from hal.core.memory.manager import MemoryManager
from hal.core.runtime.loop import LoopMetadata, run_tool_loop
from hal.core.runtime.summary import generate_summary
from hal.core.runtime.tool_factory import create_tools
from hal.core.subagent import SubagentManager
from hal.infra.providers.base import LLMProvider

if TYPE_CHECKING:
    from hal.capabilities.scheduling.cron_service import CronService
    from hal.core.memory.search import MemorySearch
    from hal.infra.config.schema import (
        EngineConfig,
        ExecToolConfig,
        HistoryConfig,
        WebFetchConfig,
        WebSearchConfig,
    )


class AgentEngine:
    """
    Unified execution engine for all interaction modes.

    Supports three execution modes:
    - COLLAB: Real-time user conversation (low latency)
    - ASYNC: Background long-running tasks (shared memory with origin)
    - OPERATOR: Scheduled monitoring (high signal-to-noise)

    After each interaction, episodes are recorded via MemoryManager.
    """

    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 20,
        web_search_api_key: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
        cron_service: "CronService | None" = None,
        restrict_to_workspace: bool = False,
        memory_manager: MemoryManager | None = None,
        summary_model: str = "default",
        summary_provider: LLMProvider | None = None,
        subagent_model: str = "default",
        subagent_provider: LLMProvider | None = None,
        memory_search: "MemorySearch | None" = None,
        auto_inject_top_k: int = 3,
        recall_min_score: float = 0.0,
        history_config: "HistoryConfig | None" = None,
        engine_config: "EngineConfig | None" = None,
        web_search_config: "WebSearchConfig | None" = None,
        web_fetch_config: "WebFetchConfig | None" = None,
    ):
        from hal.infra.config.schema import (
            EngineConfig,
            ExecToolConfig,
            HistoryConfig,
        )

        self.bus = bus
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.web_search_api_key = web_search_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.cron_service = cron_service
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
        self._pending_summaries: dict[str, asyncio.Task] = {}
        self._metrics_collector = MetricsCollector(workspace / "logs" / "context_metrics.jsonl")

        self.memory = memory_manager or MemoryManager(workspace)
        self.context = ContextBuilder(workspace, memory_manager=self.memory)

        # Resolve subagent model/provider
        sa_provider = subagent_provider or provider
        sa_model = self.model if subagent_model == "default" else subagent_model
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
        )

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
            cron_service=self.cron_service,
            memory_search=self._memory_search,
        )

    def disable_memory_search(self) -> None:
        """Disable memory search integration and unregister recall tool."""
        self._memory_search = None
        self.tools.unregister("recall")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

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
                    response = await self._dispatch(msg)
                    if response:
                        await self.bus.publish_outbound(response)
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    await self.bus.publish_outbound(
                        OutboundMessage(
                            channel=msg.channel,
                            chat_id=msg.chat_id,
                            content=f"Sorry, I encountered an error: {str(e)}",
                        )
                    )
            except asyncio.TimeoutError:
                continue

    def stop(self) -> None:
        """Stop the engine."""
        self._running = False
        logger.info("Agent engine stopping")

    async def _dispatch(self, msg: InboundMessage) -> OutboundMessage | None:
        """Route a message to the appropriate execution mode."""
        if msg.origin == "cron":
            return await self._dispatch_cron(msg)
        if msg.origin == "heartbeat":
            return await self._dispatch_heartbeat(msg)
        return await self.process_collab(msg)

    async def _dispatch_cron(self, msg: InboundMessage) -> OutboundMessage | None:
        """Handle a cron-origin message: run in OPERATOR mode, optionally deliver."""
        response = await self.process_operator(
            prompt=msg.content,
            channel=msg.channel,
            chat_id=msg.chat_id,
            session_key=msg.session_key,
            origin="cron",
        )
        if msg.metadata.get("deliver"):
            # Suppress deliver if message tool already sent during this turn
            message_tool = self.tools.get("message")
            if isinstance(message_tool, MessageTool) and message_tool.sent_in_turn:
                logger.info("[cron] message already sent via message tool, skipping deliver")
                return None

            job_name = msg.metadata.get("cron_job_name", msg.metadata.get("cron_job_id", ""))
            content = f"[⏰ cron: {job_name}]\n{response}"
            return OutboundMessage(
                channel=msg.metadata["deliver_channel"],
                chat_id=msg.metadata["deliver_chat_id"],
                content=content,
            )
        return None

    async def _dispatch_heartbeat(self, msg: InboundMessage) -> OutboundMessage | None:
        """Handle a heartbeat-origin message: run in OPERATOR mode, no delivery."""
        await self.process_operator(
            prompt=msg.content,
            channel=msg.channel,
            chat_id=msg.chat_id,
            session_key=msg.session_key,
            origin="heartbeat",
        )
        return None

    # ------------------------------------------------------------------
    # Execution modes
    # ------------------------------------------------------------------

    async def process_collab(self, msg: InboundMessage) -> OutboundMessage | None:
        """
        COLLAB mode: real-time user conversation.

        Low latency, standard tool loop, records episode after completion.
        """
        # Barrier: wait for any pending summary from a previous interaction
        if task := self._pending_summaries.pop(msg.session_key, None):
            try:
                await asyncio.wait_for(task, timeout=self._engine_config.summary_barrier_timeout_s)
            except (asyncio.TimeoutError, Exception) as e:
                logger.warning(f"Summary barrier: {e}")

        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info(f"[collab] {msg.channel}:{msg.sender_id}: {preview}")

        # Record user message
        self.memory.record_conversation(
            channel=msg.channel,
            chat_id=msg.chat_id,
            role="user",
            content=msg.content,
        )

        self._update_tool_contexts(msg.channel, msg.chat_id)

        # Get conversation history from log
        hc = self._history_config
        resolved_model = self.provider.resolve_model(self.model)
        history = self.memory.get_conversation_history(
            channel=msg.channel,
            chat_id=msg.chat_id,
            max_messages=hc.max_messages,
            include_tools=False,
            recent_full_turns=hc.recent_full_turns,
            assistant_truncate_tokens=hc.assistant_truncate_tokens,
            max_tokens=hc.max_history_tokens,
            history_days=hc.history_days,
            token_model=resolved_model,
        )

        # Pre-fetch relevant memories via semantic search
        search_results = []
        if self._memory_search:
            try:
                search_results = await self._memory_search.search(
                    msg.content,
                    top_k=self._auto_inject_top_k,
                    min_score=self._recall_min_score,
                )
            except Exception as e:
                logger.warning(f"Memory search prefetch failed: {e}")

        messages = self.context.build_messages(
            history=history,
            current_message=msg.content,
            media=msg.media if msg.media else None,
            channel=msg.channel,
            chat_id=msg.chat_id,
            mode=ExecutionMode.COLLAB,
            memory_search_results=search_results or None,
            memory_budget_tokens=(hc.memory_budget_tokens or None),
            recall_max_total_tokens=hc.recall_max_total_tokens,
            recall_max_per_item_tokens=hc.recall_max_per_item_tokens,
            token_model=resolved_model,
        )
        pre_metrics = ContextMetrics(
            timestamp=datetime.now().isoformat(),
            channel=msg.channel,
            chat_id=msg.chat_id,
            mode=ExecutionMode.COLLAB.value,
            system_prompt_chars=_content_char_len(messages[0].get("content", ""))
            if messages
            else 0,
            history_message_count=len(history),
            history_chars=sum(_content_char_len(h.get("content", "")) for h in history),
            recall_count=len(search_results),
            recall_scores=[float(getattr(r, "score", 0.0)) for r in search_results],
            recall_chars=sum(
                len(
                    trim_text_to_token_budget(
                        str(getattr(r, "content", "")),
                        hc.recall_max_per_item_tokens,
                        model=resolved_model,
                    )
                )
                for r in search_results
            ),
            current_message_chars=len(msg.content),
            total_input_chars=sum(_content_char_len(m.get("content", "")) for m in messages),
        )

        final_content, meta, injected = await self._execute_loop(
            messages,
            self.max_iterations,
            session_key=msg.session_key,
            channel=msg.channel,
            chat_id=msg.chat_id,
        )
        pre_metrics.first_prompt_tokens = meta.first_response_usage.get("prompt_tokens")
        pre_metrics.first_completion_tokens = meta.first_response_usage.get("completion_tokens")
        pre_metrics.first_total_tokens = meta.first_response_usage.get("total_tokens")
        pre_metrics.first_cache_creation_tokens = meta.first_response_usage.get(
            "cache_creation_input_tokens"
        )
        pre_metrics.first_cache_read_tokens = meta.first_response_usage.get(
            "cache_read_input_tokens"
        )
        pre_metrics.first_cache_miss_tokens = meta.first_response_usage.get(
            "prompt_cache_miss_tokens"
        )
        pre_metrics.total_cache_creation_tokens = meta.cache_creation_tokens
        pre_metrics.total_cache_read_tokens = meta.cache_read_tokens
        pre_metrics.total_cache_miss_tokens = meta.cache_miss_tokens
        pre_metrics.loop_iterations = meta.iterations
        pre_metrics.tools_used = list(meta.tools_used)
        pre_metrics.spawn_count = meta.tool_call_counts.get("spawn", 0)
        pre_metrics.has_side_effects = meta.has_side_effects
        pre_metrics.spawn_total_tokens = _extract_spawn_total_tokens(messages)
        self._record_metrics(pre_metrics)

        # Defensive fallback — should rarely trigger after loop-level nudge.
        if not final_content:
            final_content = "(No response generated.)"

        # Record assistant response
        self.memory.record_conversation(
            channel=msg.channel,
            chat_id=msg.chat_id,
            role="assistant",
            content=final_content,
        )

        # Trigger async summary if qualifying loop
        summary_task = self._trigger_summary(meta, final_content, msg.channel, msg.chat_id)
        if summary_task:
            self._pending_summaries[msg.session_key] = summary_task

        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info(f"[collab] response: {preview}")

        # Suppress final outbound if the message tool already sent during this turn
        message_tool = self.tools.get("message")
        if isinstance(message_tool, MessageTool) and message_tool.sent_in_turn:
            logger.info(
                "[collab] message already sent via message tool, suppressing final outbound"
            )
            return None

        return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=final_content)

    async def process_operator(
        self,
        prompt: str,
        channel: str = "cli",
        chat_id: str = "direct",
        session_key: str | None = None,
        origin: str = "user",
    ) -> str:
        """
        OPERATOR mode: scheduled monitoring.

        Used by cron jobs and heartbeat. Higher signal-to-noise — only
        produces output when there's something actionable.
        """
        s_key = session_key or f"{channel}:{chat_id}"

        logger.info(f"[operator] {s_key}: {prompt[:60]}...")

        # Record operator prompt
        self.memory.record_conversation(
            channel=channel,
            chat_id=chat_id,
            role="user",
            content=prompt,
            origin=origin,
        )

        self._update_tool_contexts(channel, chat_id)

        # Get conversation history from log
        hc = self._history_config
        resolved_model = self.provider.resolve_model(self.model)
        history = self.memory.get_conversation_history(
            channel=channel,
            chat_id=chat_id,
            max_messages=hc.max_messages,
            include_tools=False,
            recent_full_turns=hc.recent_full_turns,
            assistant_truncate_tokens=hc.assistant_truncate_tokens,
            max_tokens=hc.max_history_tokens,
            history_days=hc.history_days,
            token_model=resolved_model,
        )

        messages = self.context.build_messages(
            history=history,
            current_message=prompt,
            channel=channel,
            chat_id=chat_id,
            mode=ExecutionMode.OPERATOR,
            memory_budget_tokens=(hc.memory_budget_tokens or None),
            recall_max_total_tokens=hc.recall_max_total_tokens,
            recall_max_per_item_tokens=hc.recall_max_per_item_tokens,
            token_model=resolved_model,
        )
        pre_metrics = ContextMetrics(
            timestamp=datetime.now().isoformat(),
            channel=channel,
            chat_id=chat_id,
            mode=ExecutionMode.OPERATOR.value,
            system_prompt_chars=_content_char_len(messages[0].get("content", ""))
            if messages
            else 0,
            history_message_count=len(history),
            history_chars=sum(_content_char_len(h.get("content", "")) for h in history),
            recall_count=0,
            recall_scores=[],
            recall_chars=0,
            current_message_chars=len(prompt),
            total_input_chars=sum(_content_char_len(m.get("content", "")) for m in messages),
        )

        # Operator mode uses fewer iterations
        max_iter = min(self.max_iterations, self._engine_config.operator_max_iterations)
        final_content, meta, _ = await self._execute_loop(
            messages,
            max_iter,
            session_key=s_key,
            channel=channel,
            chat_id=chat_id,
        )
        pre_metrics.first_prompt_tokens = meta.first_response_usage.get("prompt_tokens")
        pre_metrics.first_completion_tokens = meta.first_response_usage.get("completion_tokens")
        pre_metrics.first_total_tokens = meta.first_response_usage.get("total_tokens")
        pre_metrics.first_cache_creation_tokens = meta.first_response_usage.get(
            "cache_creation_input_tokens"
        )
        pre_metrics.first_cache_read_tokens = meta.first_response_usage.get(
            "cache_read_input_tokens"
        )
        pre_metrics.first_cache_miss_tokens = meta.first_response_usage.get(
            "prompt_cache_miss_tokens"
        )
        pre_metrics.total_cache_creation_tokens = meta.cache_creation_tokens
        pre_metrics.total_cache_read_tokens = meta.cache_read_tokens
        pre_metrics.total_cache_miss_tokens = meta.cache_miss_tokens
        pre_metrics.loop_iterations = meta.iterations
        pre_metrics.tools_used = list(meta.tools_used)
        pre_metrics.spawn_count = meta.tool_call_counts.get("spawn", 0)
        pre_metrics.has_side_effects = meta.has_side_effects
        pre_metrics.spawn_total_tokens = _extract_spawn_total_tokens(messages)
        self._record_metrics(pre_metrics)

        if final_content is None:
            final_content = "Monitoring complete. Nothing to report."

        # Record operator response
        self.memory.record_conversation(
            channel=channel,
            chat_id=chat_id,
            role="assistant",
            content=final_content,
            origin=origin,
        )

        # Trigger async summary if qualifying loop (no barrier needed for operator)
        self._trigger_summary(meta, final_content, channel, chat_id)

        return final_content

    # ------------------------------------------------------------------
    # Mid-loop message injection
    # ------------------------------------------------------------------

    def _drain_pending_for_session(self, session_key: str) -> list[InboundMessage]:
        """Non-blocking drain of inbound queue for messages matching session_key.

        Non-matching messages are re-queued in their original order.
        Safe because the engine processes one dispatch at a time.
        """
        matching: list[InboundMessage] = []
        others: list[InboundMessage] = []

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

    # ------------------------------------------------------------------
    # Core tool loop (delegates to shared runtime)
    # ------------------------------------------------------------------

    async def _execute_loop(
        self,
        messages: list[dict[str, Any]],
        max_iterations: int,
        session_key: str | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
    ) -> tuple[str | None, LoopMetadata, list[InboundMessage]]:
        """Run the LLM tool-calling loop via the shared runtime.

        Returns:
            Tuple of (final_content, loop_metadata, injected_messages).
        """
        hooks = _EngineLoopHooks(
            engine=self,
            session_key=session_key,
            channel=channel,
            chat_id=chat_id,
        )

        final_content, meta = await run_tool_loop(
            provider=self.provider,
            model=self.model,
            tools=self.tools,
            messages=messages,
            max_iterations=max_iterations,
            hooks=hooks,
            add_assistant_message=self.context.add_assistant_message,
            add_tool_result=self.context.add_tool_result,
        )

        return final_content, meta, hooks.injected

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _summary_model_id(self) -> str:
        """Resolve the model to use for summary generation."""
        return self.model if self._summary_model == "default" else self._summary_model

    def _trigger_summary(
        self, meta: LoopMetadata, final_content: str, channel: str, chat_id: str
    ) -> asyncio.Task | None:
        """Create an async summary task if the loop qualifies."""
        if not meta.needs_summary:
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
        message_tool = self.tools.get("message")
        if isinstance(message_tool, MessageTool):
            message_tool.set_context(channel, chat_id)

        spawn_tool = self.tools.get("spawn")
        if isinstance(spawn_tool, SpawnTool):
            spawn_tool.set_context(channel, chat_id)

        cron_tool = self.tools.get("cron")
        if isinstance(cron_tool, CronTool):
            cron_tool.set_context(channel, chat_id)

    def _record_metrics(self, metrics: ContextMetrics) -> None:
        """Best-effort metrics recording without affecting user flows."""
        try:
            self._metrics_collector.record(metrics)
        except Exception as e:
            logger.warning(f"Failed to record context metrics: {e}")

    def _inspect_history_window(self, history_days: int) -> list[dict[str, Any]]:
        """Build a lightweight debug view of daily log files scanned for history."""
        days = max(history_days, 1)
        today = date.today()
        log_dir = self.memory.daily_log.data_dir
        window: list[dict[str, Any]] = []
        for offset in range(days - 1, -1, -1):
            day = today - timedelta(days=offset)
            day_str = day.isoformat()
            path = log_dir / f"{day_str}.jsonl"
            window.append({"date": day_str, "exists": path.exists()})
        return window

    async def inspect_context(
        self,
        *,
        channel: str,
        chat_id: str,
        current_message: str,
    ) -> dict[str, Any]:
        """Build the current COLLAB context and return debug-friendly metadata.

        This does not mutate memory or execute any LLM/tool calls.
        """
        hc = self._history_config
        resolved_model = self.provider.resolve_model(self.model)
        history = self.memory.get_conversation_history(
            channel=channel,
            chat_id=chat_id,
            max_messages=hc.max_messages,
            include_tools=False,
            recent_full_turns=hc.recent_full_turns,
            assistant_truncate_tokens=hc.assistant_truncate_tokens,
            max_tokens=hc.max_history_tokens,
            history_days=hc.history_days,
            token_model=resolved_model,
        )

        search_results = []
        if self._memory_search and current_message.strip():
            try:
                search_results = await self._memory_search.search(
                    current_message,
                    top_k=self._auto_inject_top_k,
                    min_score=self._recall_min_score,
                )
            except Exception as e:
                logger.warning(f"Memory search prefetch failed during inspect: {e}")

        messages = self.context.build_messages(
            history=history,
            current_message=current_message,
            channel=channel,
            chat_id=chat_id,
            mode=ExecutionMode.COLLAB,
            memory_search_results=search_results or None,
            memory_budget_tokens=(hc.memory_budget_tokens or None),
            recall_max_total_tokens=hc.recall_max_total_tokens,
            recall_max_per_item_tokens=hc.recall_max_per_item_tokens,
            token_model=resolved_model,
        )

        tools = self.tools.get_definitions()
        token_estimate = _estimate_prompt_tokens(resolved_model, messages, tools)
        history_tokens = _estimate_messages_tokens(resolved_model, history)
        system_prompt_tokens = _estimate_messages_tokens(resolved_model, messages[:1])
        per_message_tokens = _estimate_per_message_tokens(resolved_model, messages)
        history_window = self._inspect_history_window(hc.history_days)

        # Deduplicate recall items at engine layer (by source+heading+source_type).
        seen_recall: set[tuple[str, str, str]] = set()
        recall_items: list[dict[str, Any]] = []
        for r in search_results:
            key = (
                getattr(r, "source", ""),
                getattr(r, "heading", ""),
                getattr(r, "source_type", "raw"),
            )
            if key in seen_recall:
                continue
            seen_recall.add(key)
            recall_items.append(
                {
                    "source": key[0],
                    "heading": key[1],
                    "score": float(getattr(r, "score", 0.0)),
                    "source_type": key[2],
                }
            )

        # Build per-message summaries (role + char count + short preview).
        preview_len = 80
        message_summaries: list[dict[str, Any]] = []
        for idx, msg in enumerate(messages):
            content = msg.get("content", "")
            chars = _content_char_len(content)
            tokens = (
                per_message_tokens[idx]
                if idx < len(per_message_tokens)
                else rough_tokens_from_chars(chars)
            )
            preview_src = content if isinstance(content, str) else str(content)
            preview = preview_src[:preview_len].replace("\n", " ")
            if len(preview_src) > preview_len:
                preview += "…"
            message_summaries.append(
                {
                    "role": msg.get("role", ""),
                    "chars": chars,
                    "tokens": tokens,
                    "preview": preview,
                }
            )

        sys_chars = _content_char_len(messages[0].get("content", "")) if messages else 0

        return {
            "channel": channel,
            "chat_id": chat_id,
            "mode": ExecutionMode.COLLAB.value,
            "model": self.model,
            "messages": messages,
            "message_summaries": message_summaries,
            "history_message_count": len(history),
            "history_chars": sum(_content_char_len(h.get("content", "")) for h in history),
            "history_tokens": history_tokens,
            "recall_count": len(recall_items),
            "recall_items": recall_items,
            "system_prompt_chars": sys_chars,
            "system_prompt_tokens": system_prompt_tokens,
            "total_input_chars": sum(_content_char_len(m.get("content", "")) for m in messages),
            "total_input_tokens": token_estimate.get("messages_only", 0),
            "history_config": {
                "history_days": hc.history_days,
                "max_messages": hc.max_messages,
                "max_history_tokens": hc.max_history_tokens,
            },
            "history_window": history_window,
            "token_estimate": token_estimate,
        }

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
    ) -> str:
        """
        Process a message directly (for CLI or cron usage).

        Routes to the appropriate execution mode based on context:
        - CLI/direct messages → COLLAB
        - Cron/heartbeat → OPERATOR
        """
        if session_key.startswith("cron:") or session_key == "heartbeat":
            return await self.process_operator(
                prompt=content, channel=channel, chat_id=chat_id, session_key=session_key
            )

        msg = InboundMessage(channel=channel, sender_id="user", chat_id=chat_id, content=content)
        response = await self.process_collab(msg)
        return response.content if response else ""


class _EngineLoopHooks:
    """Loop hooks for the main AgentEngine.

    Handles mid-loop message injection, memory recording, and
    background subagent result collection.
    """

    # System reminder injected periodically to keep HaL in manager mindset.
    _REMINDER = (
        "[System Reminder]\n"
        "You are a strategist, not an executor.\n"
        "Is the current direction correct? Is there a better approach?\n"
        "If unsure, pause and reassess or ask the user before continuing.\n"
        "Do not respond to this reminder — it is automatic."
    )

    _REMINDER_INTERVAL = 5  # inject every N total tool calls
    _INTERRUPT_THRESHOLD = 3  # skip tool execution when N+ user messages queued

    def __init__(
        self,
        engine: AgentEngine,
        session_key: str | None,
        channel: str | None,
        chat_id: str | None,
    ):
        self._engine = engine
        self._session_key = session_key
        self._channel = channel
        self._chat_id = chat_id
        self.injected: list[InboundMessage] = []
        self._last_reminder_at: int = 0
        self._buffered_pending: list[InboundMessage] = []

    def _inject_pending(
        self, messages: list[dict[str, Any]], pending_msgs: list[InboundMessage]
    ) -> None:
        """Inject pending user messages into the conversation."""
        for pending in pending_msgs:
            prefixed = f"[User follow-up while you are working] {pending.content}"
            messages.append({"role": "user", "content": prefixed})
            self.injected.append(pending)
            logger.info(f"[inject] mid-loop message from {pending.sender_id}")

            if self._channel and self._chat_id:
                self._engine.memory.record_conversation(
                    channel=self._channel,
                    chat_id=self._chat_id,
                    role="user",
                    content=prefixed,
                )

    def before_llm_call(self, messages: list[dict[str, Any]], meta: LoopMetadata) -> None:
        """Inject pending user messages and periodic system reminders."""
        # First: inject buffered messages from interrupt detection
        if self._buffered_pending:
            self._inject_pending(messages, self._buffered_pending)
            self._buffered_pending.clear()

        # Then: drain fresh messages
        if self._session_key:
            fresh = self._engine._drain_pending_for_session(self._session_key)
            if fresh:
                self._inject_pending(messages, fresh)

        # Inject system reminder when interval is reached
        if self._should_inject_reminder(meta):
            messages.append({"role": "user", "content": self._REMINDER})
            self._last_reminder_at = meta.total_tool_calls

    def _should_inject_reminder(self, meta: LoopMetadata) -> bool:
        """Check if a system reminder should be injected."""
        if meta.total_tool_calls == 0:
            return False
        return (
            meta.total_tool_calls % self._REMINDER_INTERVAL == 0
            and meta.total_tool_calls > self._last_reminder_at
        )

    def on_tool_result(
        self,
        tool_name: str,
        tool_id: str,
        arguments: dict[str, Any],
        result: str,
        messages: list[dict[str, Any]],
        meta: LoopMetadata,
    ) -> None:
        """Record tool calls to memory."""
        if not (self._channel and self._chat_id):
            return

        self._engine.memory.record_conversation(
            channel=self._channel,
            chat_id=self._chat_id,
            role="tool",
            content=(
                f"Calling {tool_name} with arguments: {json.dumps(arguments, ensure_ascii=False)}"
            ),
            tool_name=tool_name,
            tool_result=result,
        )

        # Persist sync spawn results as user-injection so they survive
        # include_tools=False in future history rebuilds.
        if tool_name == "spawn":
            bg = arguments.get("background", False)
            if not bg:
                label = arguments.get("label", arguments.get("task", "")[:40])
                parsed = _split_subagent_tool_result(result)
                self._engine.memory.record_conversation(
                    channel=self._channel,
                    chat_id=self._chat_id,
                    role="user",
                    content=_build_subagent_injection(
                        label=label,
                        content=parsed.content,
                        status=parsed.status,
                        background=False,
                        record_id=parsed.record_id,
                        artifact_path=parsed.artifact_path,
                        total_tokens=parsed.total_tokens,
                        tools_used=parsed.tools_used,
                        tool_call_counts=parsed.tool_call_counts,
                        has_side_effects=parsed.has_side_effects,
                        files_modified=parsed.files_modified,
                        commands_run=parsed.commands_run,
                        tool_errors=parsed.tool_errors,
                        missing_artifacts=parsed.missing_artifacts,
                        max_tokens=_SUBAGENT_HISTORY_MAX_TOKENS,
                    ),
                    entry_type="injection",
                )

    async def on_no_tool_calls(
        self,
        messages: list[dict[str, Any]],
        response: Any,
        meta: LoopMetadata,
    ) -> bool:
        """Collect pending background subagent results before finalizing."""
        pending = await self._engine.subagents.await_pending()
        if not pending:
            return False

        # Inject subagent results and let LLM incorporate them
        messages = self._engine.context.add_assistant_message(
            messages,
            response.content,
            [],
            reasoning_content=response.reasoning_content,
        )
        for label, details in pending:
            content = getattr(details, "content", str(details))
            artifact_path = getattr(details, "artifact_path", None)
            total_tokens = getattr(details, "total_tokens", 0)
            record_id = getattr(details, "record_id", None)
            status = getattr(details, "status", None) or (
                "failed" if content.startswith("Error:") else "completed"
            )
            tools_used = list(getattr(details, "tools_used", []) or [])
            tool_call_counts = dict(getattr(details, "tool_call_counts", {}) or {})
            has_side_effects = bool(getattr(details, "has_side_effects", False))
            files_modified = list(getattr(details, "files_modified", []) or [])
            commands_run = list(getattr(details, "commands_run", []) or [])
            tool_errors = list(getattr(details, "tool_errors", []) or [])
            missing_artifacts = [str(p) for p in (getattr(details, "missing_artifacts", []) or [])]
            runtime_inject = _build_subagent_injection(
                label=label,
                content=content,
                status=status,
                background=True,
                record_id=record_id,
                artifact_path=str(artifact_path) if artifact_path else None,
                total_tokens=total_tokens,
                tools_used=tools_used,
                tool_call_counts=tool_call_counts,
                has_side_effects=has_side_effects,
                files_modified=files_modified,
                commands_run=commands_run,
                tool_errors=tool_errors,
                missing_artifacts=missing_artifacts,
                max_tokens=_SUBAGENT_RUNTIME_MAX_TOKENS,
            )
            messages.append({"role": "user", "content": runtime_inject})
            logger.info(f"[inject] subagent result: {label} ({status})")

            if self._channel and self._chat_id:
                history_inject = _build_subagent_injection(
                    label=label,
                    content=content,
                    status=status,
                    background=True,
                    record_id=record_id,
                    artifact_path=str(artifact_path) if artifact_path else None,
                    total_tokens=total_tokens,
                    tools_used=tools_used,
                    tool_call_counts=tool_call_counts,
                    has_side_effects=has_side_effects,
                    files_modified=files_modified,
                    commands_run=commands_run,
                    tool_errors=tool_errors,
                    missing_artifacts=missing_artifacts,
                    max_tokens=_SUBAGENT_HISTORY_MAX_TOKENS,
                )
                self._engine.memory.record_conversation(
                    channel=self._channel,
                    chat_id=self._chat_id,
                    role="user",
                    content=history_inject,
                    entry_type="injection",
                )
        return True

    async def on_loop_exhausted(
        self,
        messages: list[dict[str, Any]],
        meta: LoopMetadata,
    ) -> str | None:
        return None

    async def on_tool_calls_start(
        self,
        tool_calls: list[Any],
        assistant_content: str | None,
        meta: LoopMetadata,
    ) -> bool | None:
        """Check for user interrupt, then optionally send progress."""
        # Drain and buffer pending messages for interrupt detection
        if self._session_key:
            fresh = self._engine._drain_pending_for_session(self._session_key)
            self._buffered_pending.extend(fresh)

        # If buffered messages reach threshold, skip tool execution
        if len(self._buffered_pending) >= self._INTERRUPT_THRESHOLD:
            count = len(self._buffered_pending)
            logger.info(
                f"[interrupt] skipping {len(tool_calls)} tool calls: {count} user messages buffered"
            )
            return True

        # Normal path: send progress notification
        if not (self._channel and self._chat_id):
            return None

        # Hide message-tool progress in chat channels to avoid duplicated user-facing output:
        # the message tool already sends its own outbound message.
        visible_tool_calls = [tc for tc in tool_calls if getattr(tc, "name", "") != "message"]
        if not visible_tool_calls:
            return None

        text = _format_progress_message(assistant_content, visible_tool_calls)
        if not text:
            return None

        await self._engine.bus.publish_outbound(
            OutboundMessage(
                channel=self._channel,
                chat_id=self._chat_id,
                content=text,
                metadata={"progress": True},
            )
        )
        return None


_THINK_RE = re.compile(r"<think>.*?</think>|<think>.*$", re.DOTALL)
_SUBAGENT_TOKEN_RE = re.compile(r"\[Subagent Total Tokens\]\s*(\d+)")
_SUBAGENT_ARTIFACT_RE = re.compile(r"^\[Subagent Artifact\]\s*(.+)$", re.MULTILINE)
_SUBAGENT_RECORD_RE = re.compile(r"^\[Subagent Record ID\]\s*(.+)$", re.MULTILINE)
_SUBAGENT_STATUS_RE = re.compile(r"^\[Subagent Status\]\s*(.+)$", re.MULTILINE)
_SUBAGENT_TOOLS_USED_RE = re.compile(r"^\[Subagent Tools Used\]\s*(.+)$", re.MULTILINE)
_SUBAGENT_TOOL_COUNTS_RE = re.compile(r"^\[Subagent Tool Counts\]\s*(.+)$", re.MULTILINE)
_SUBAGENT_HAS_SIDE_EFFECTS_RE = re.compile(r"^\[Subagent Has Side Effects\]\s*(.+)$", re.MULTILINE)
_SUBAGENT_FILES_MODIFIED_RE = re.compile(r"^\[Subagent Files Modified\]\s*(.+)$", re.MULTILINE)
_SUBAGENT_COMMANDS_RUN_RE = re.compile(r"^\[Subagent Commands Run\]\s*(.+)$", re.MULTILINE)
_SUBAGENT_TOOL_ERRORS_RE = re.compile(r"^\[Subagent Tool Errors\]\s*(.+)$", re.MULTILINE)
_SUBAGENT_MISSING_ARTIFACTS_RE = re.compile(
    r"^\[Subagent Missing Artifacts\]\s*(.+)$", re.MULTILINE
)
_SUBAGENT_HISTORY_MAX_TOKENS = 200
# 0 = no truncation for same-turn runtime injection to main agent.
_SUBAGENT_RUNTIME_MAX_TOKENS = 0


@dataclass
class ParsedSubagentResult:
    content: str
    artifact_path: str | None
    total_tokens: int
    record_id: str | None
    status: str
    tools_used: list[str]
    tool_call_counts: dict[str, int]
    has_side_effects: bool
    files_modified: list[str]
    commands_run: list[str]
    tool_errors: list[str]
    missing_artifacts: list[str]


def _format_progress_message(
    assistant_content: str | None,
    tool_calls: list[Any],
) -> str | None:
    """Build a progress message combining intent and tool calls.

    Format: optional cleaned content + tool call hints.
    Example:
        让我检查分支状态
        ↳ exec('git status')
    """
    parts: list[str] = []

    if assistant_content:
        cleaned = _THINK_RE.sub("", assistant_content).strip()
        if cleaned:
            parts.append(cleaned)

    for tc in tool_calls or []:
        summary = _summarize_args(tc.arguments)
        parts.append(f"↳ {tc.name}({summary})")

    return "\n".join(parts) if parts else None


def _summarize_args(args: dict[str, Any] | None) -> str:
    """Produce a short argument summary for progress display."""
    if not args:
        return ""
    # Prefer common descriptive keys
    for key in ("query", "task", "command", "path", "url", "content", "pattern"):
        if key in args:
            val = str(args[key])
            if len(val) > 60:
                val = val[:57] + "..."
            return repr(val)
    # Fallback: first key's value
    first_val = str(next(iter(args.values())))
    if len(first_val) > 60:
        first_val = first_val[:57] + "..."
    return repr(first_val)


def _content_char_len(content: Any) -> int:
    """Estimate character length for heterogeneous message content payloads."""
    if content is None:
        return 0
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(_content_char_len(item) for item in content)
    if isinstance(content, dict):
        # Multimodal message parts store text under `text`.
        if "text" in content and isinstance(content["text"], str):
            return len(content["text"])
        return sum(_content_char_len(v) for v in content.values())
    return len(str(content))


def _estimate_messages_tokens(model: str, messages: list[dict[str, Any]]) -> int:
    """Estimate token count for a list of messages."""
    if not messages:
        return 0

    fallback = rough_tokens_from_chars(
        sum(_content_char_len(m.get("content", "")) for m in messages)
    )
    try:
        import litellm

        return int(litellm.token_counter(model=model, messages=messages))
    except Exception:
        return fallback


def _estimate_per_message_tokens(model: str, messages: list[dict[str, Any]]) -> list[int]:
    """Estimate token count for each message (for context inspector display)."""
    fallback = [rough_tokens_from_chars(_content_char_len(m.get("content", ""))) for m in messages]
    if not messages:
        return fallback

    try:
        import litellm

        return [int(litellm.token_counter(model=model, messages=[m])) for m in messages]
    except Exception:
        return fallback


def _estimate_prompt_tokens(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> dict[str, Any]:
    """Estimate input token usage for context inspection output.

    Prefers ``litellm.token_counter`` for model-aware counting and falls back
    to a rough chars/4 estimate when unavailable.
    """
    msg_chars = sum(_content_char_len(m.get("content", "")) for m in messages)
    tools_chars = len(json.dumps(tools, ensure_ascii=False))
    fallback = {
        "method": "chars_div_4",
        "messages_only": rough_tokens_from_chars(msg_chars),
        "with_tools": rough_tokens_from_chars(msg_chars + tools_chars),
        "tools_only": rough_tokens_from_chars(tools_chars),
        "error": None,
    }

    try:
        import litellm

        messages_only = int(litellm.token_counter(model=model, messages=messages))
        with_tools = int(litellm.token_counter(model=model, messages=messages, tools=tools))
        return {
            "method": "litellm.token_counter",
            "messages_only": messages_only,
            "with_tools": with_tools,
            "tools_only": max(with_tools - messages_only, 0),
            "error": None,
        }
    except Exception as e:
        fallback["error"] = str(e)
        return fallback


def _extract_spawn_total_tokens(messages: list[dict[str, Any]]) -> int:
    """Sum known spawn token usage tags from tool message content."""
    total = 0
    for msg in messages:
        content = str(msg.get("content", ""))
        for match in _SUBAGENT_TOKEN_RE.findall(content):
            total += int(match)
    return total


def _split_subagent_tool_result(result: str) -> ParsedSubagentResult:
    """Split sync spawn tool result into content + structured metadata."""
    artifact_match = _SUBAGENT_ARTIFACT_RE.search(result)
    artifact_path = artifact_match.group(1).strip() if artifact_match else None
    record_match = _SUBAGENT_RECORD_RE.search(result)
    record_id = record_match.group(1).strip() if record_match else None
    status_match = _SUBAGENT_STATUS_RE.search(result)
    status = status_match.group(1).strip().lower() if status_match else ""

    total_tokens = 0
    for token in _SUBAGENT_TOKEN_RE.findall(result):
        total_tokens += int(token)

    tools_used = _parse_json_list_marker(_SUBAGENT_TOOLS_USED_RE.search(result))
    tool_call_counts = _parse_json_dict_marker(_SUBAGENT_TOOL_COUNTS_RE.search(result))
    has_side_effects = _parse_bool_marker(_SUBAGENT_HAS_SIDE_EFFECTS_RE.search(result))
    files_modified = _parse_json_list_marker(_SUBAGENT_FILES_MODIFIED_RE.search(result))
    commands_run = _parse_json_list_marker(_SUBAGENT_COMMANDS_RUN_RE.search(result))
    tool_errors = _parse_json_list_marker(_SUBAGENT_TOOL_ERRORS_RE.search(result))
    missing_artifacts = _parse_json_list_marker(_SUBAGENT_MISSING_ARTIFACTS_RE.search(result))

    cleaned_lines: list[str] = []
    marker_prefixes = (
        "[Subagent Artifact]",
        "[Subagent Record ID]",
        "[Subagent Log]",
        "[Subagent Total Tokens]",
        "[Subagent Status]",
        "[Subagent Tools Used]",
        "[Subagent Tool Counts]",
        "[Subagent Has Side Effects]",
        "[Subagent Files Modified]",
        "[Subagent Commands Run]",
        "[Subagent Tool Errors]",
        "[Subagent Missing Artifacts]",
    )
    for line in result.splitlines():
        if line.startswith(marker_prefixes):
            continue
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines).strip() or result.strip()

    if not status:
        status = "failed" if cleaned.startswith("Error:") else "completed"

    return ParsedSubagentResult(
        content=cleaned,
        artifact_path=artifact_path,
        total_tokens=total_tokens,
        record_id=record_id,
        status=status,
        tools_used=tools_used,
        tool_call_counts=tool_call_counts,
        has_side_effects=has_side_effects,
        files_modified=files_modified,
        commands_run=commands_run,
        tool_errors=tool_errors,
        missing_artifacts=missing_artifacts,
    )


def _parse_json_list_marker(match: re.Match[str] | None) -> list[str]:
    """Parse a marker payload as a list with graceful fallbacks."""
    if not match:
        return []
    raw = match.group(1).strip()
    if not raw:
        return []
    try:
        value = json.loads(raw)
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
    except Exception:
        pass
    return [part.strip() for part in raw.split(",") if part.strip()]


def _parse_json_dict_marker(match: re.Match[str] | None) -> dict[str, int]:
    """Parse a marker payload as a dict[str, int]."""
    if not match:
        return {}
    raw = match.group(1).strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(value, dict):
        return {}
    parsed: dict[str, int] = {}
    for k, v in value.items():
        if isinstance(v, int):
            parsed[str(k)] = v
        elif isinstance(v, float):
            parsed[str(k)] = int(v)
    return parsed


def _parse_bool_marker(match: re.Match[str] | None) -> bool:
    """Parse a marker payload as a boolean value."""
    if not match:
        return False
    return match.group(1).strip().lower() in {"1", "true", "yes", "y"}


def _build_subagent_injection(
    *,
    label: str,
    content: str,
    status: str,
    background: bool,
    record_id: str | None,
    artifact_path: str | None,
    total_tokens: int,
    tools_used: list[str] | None = None,
    tool_call_counts: dict[str, int] | None = None,
    has_side_effects: bool = False,
    files_modified: list[str] | None = None,
    commands_run: list[str] | None = None,
    tool_errors: list[str] | None = None,
    missing_artifacts: list[str] | None = None,
    max_tokens: int = _SUBAGENT_HISTORY_MAX_TOKENS,
) -> str:
    """Build compact subagent injection content for next-loop context."""
    is_error = status in {"failed", "error"} or content.startswith("Error:")
    body = content
    truncated = False
    if not is_error and max_tokens > 0:
        trimmed = trim_text_to_token_budget(body, max_tokens, suffix=" [...]")
        truncated = trimmed != body
        body = trimmed

    if background:
        text = f"[Background subagent '{label}' {status}]\n\nResult:\n{body}"
    else:
        text = f"[Subagent Result: {label}]\n\n{body}"

    if truncated:
        text += "\n\n[Full result saved to subagent artifact file]"
    if record_id:
        text += f"\n[Subagent Record ID] {record_id}"
    if artifact_path:
        text += f"\n[Subagent Artifact] {artifact_path}"
    if total_tokens:
        text += f"\n[Subagent Total Tokens] {total_tokens}"
    text += f"\n[Subagent Status] {status}"

    if tools_used:
        text += f"\n[Subagent Tools Used] {json.dumps(tools_used, ensure_ascii=False)}"
    if tool_call_counts:
        text += f"\n[Subagent Tool Counts] {json.dumps(tool_call_counts, ensure_ascii=False)}"
    text += f"\n[Subagent Has Side Effects] {'true' if has_side_effects else 'false'}"
    if files_modified:
        text += f"\n[Subagent Files Modified] {json.dumps(files_modified, ensure_ascii=False)}"
    if commands_run:
        text += f"\n[Subagent Commands Run] {json.dumps(commands_run, ensure_ascii=False)}"
    if tool_errors:
        text += f"\n[Subagent Tool Errors] {json.dumps(tool_errors, ensure_ascii=False)}"
    if missing_artifacts:
        text += (
            f"\n[Subagent Missing Artifacts] {json.dumps(missing_artifacts, ensure_ascii=False)}"
        )
    return text


# Backward compatibility alias
AgentLoop = AgentEngine
