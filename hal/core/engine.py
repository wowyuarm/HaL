"""AgentEngine — unified execution engine for all interaction modes."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from hal.bus.events import InboundMessage, OutboundMessage
from hal.bus.queue import MessageBus
from hal.capabilities.tools.message import MessageTool
from hal.capabilities.tools.schedule import CronTool
from hal.capabilities.tools.spawn import SpawnTool
from hal.core.context.builder import ContextBuilder, ExecutionMode
from hal.core.memory.manager import MemoryManager
from hal.core.runtime.loop import LoopMetadata, run_tool_loop
from hal.core.runtime.summary import generate_summary
from hal.core.runtime.tool_factory import create_tools
from hal.core.subagent import SubagentManager
from hal.infra.providers.base import LLMProvider

if TYPE_CHECKING:
    from hal.capabilities.scheduling.cron_service import CronService
    from hal.core.memory.search import MemorySearch
    from hal.infra.config.schema import ExecToolConfig, HistoryConfig


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
        history_config: "HistoryConfig | None" = None,
    ):
        from hal.infra.config.schema import ExecToolConfig, HistoryConfig

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
        self._history_config = history_config or HistoryConfig()
        self._pending_summaries: dict[str, asyncio.Task] = {}

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
            bus=self.bus,
            subagent_manager=self.subagents,
            cron_service=self.cron_service,
            memory_search=self._memory_search,
        )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Run the engine, processing messages from the bus."""
        self._running = True
        logger.info("Agent engine started")

        while self._running:
            try:
                msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
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
                await asyncio.wait_for(task, timeout=10.0)
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
        history = self.memory.get_conversation_history(
            channel=msg.channel,
            chat_id=msg.chat_id,
            max_messages=hc.max_messages,
            include_tools=False,
            recent_full_turns=hc.recent_full_turns,
            assistant_truncate_chars=hc.assistant_truncate_chars,
        )

        # Pre-fetch relevant memories via semantic search
        search_results = []
        if self._memory_search:
            try:
                search_results = await self._memory_search.search(
                    msg.content, top_k=self._auto_inject_top_k
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
        )

        final_content, meta, injected = await self._execute_loop(
            messages,
            self.max_iterations,
            session_key=msg.session_key,
            channel=msg.channel,
            chat_id=msg.chat_id,
        )

        if final_content is None:
            final_content = "I've completed processing but have no response to give."

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
        history = self.memory.get_conversation_history(
            channel=channel,
            chat_id=chat_id,
            max_messages=hc.max_messages,
            include_tools=False,
            recent_full_turns=hc.recent_full_turns,
            assistant_truncate_chars=hc.assistant_truncate_chars,
        )

        messages = self.context.build_messages(
            history=history,
            current_message=prompt,
            channel=channel,
            chat_id=chat_id,
            mode=ExecutionMode.OPERATOR,
        )

        # Operator mode uses fewer iterations
        max_iter = min(self.max_iterations, 10)
        final_content, meta, _ = await self._execute_loop(
            messages,
            max_iter,
            session_key=s_key,
            channel=channel,
            chat_id=chat_id,
        )

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

    def before_llm_call(self, messages: list[dict[str, Any]], meta: LoopMetadata) -> None:
        """Inject any messages that arrived mid-execution."""
        if not self._session_key:
            return
        for pending in self._engine._drain_pending_for_session(self._session_key):
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
                self._engine.memory.record_conversation(
                    channel=self._channel,
                    chat_id=self._chat_id,
                    role="user",
                    content=f"[Subagent Result: {label}]\n\n{result}",
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
        for label, result in pending:
            status = "failed" if result.startswith("Error:") else "completed"
            inject = f"[Background subagent '{label}' {status}]\n\nResult:\n{result}"
            messages.append({"role": "user", "content": inject})
            logger.info(f"[inject] subagent result: {label} ({status})")

            if self._channel and self._chat_id:
                self._engine.memory.record_conversation(
                    channel=self._channel,
                    chat_id=self._chat_id,
                    role="user",
                    content=inject,
                    entry_type="injection",
                )
        return True

    async def on_loop_exhausted(
        self,
        messages: list[dict[str, Any]],
        meta: LoopMetadata,
    ) -> str | None:
        return None


# Backward compatibility alias
AgentLoop = AgentEngine
