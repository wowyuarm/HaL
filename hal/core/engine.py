"""AgentEngine — unified execution engine for all interaction modes."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from hal.bus.events import InboundMessage, OutboundMessage
from hal.bus.queue import MessageBus
from hal.capabilities.tools.exec import ExecTool
from hal.capabilities.tools.fs import FsTool
from hal.capabilities.tools.message import MessageTool
from hal.capabilities.tools.registry import ToolRegistry
from hal.capabilities.tools.schedule import CronTool
from hal.capabilities.tools.spawn import SpawnTool
from hal.capabilities.tools.web import WebFetchTool, WebSearchTool
from hal.core.context.builder import ContextBuilder, ExecutionMode
from hal.core.memory.manager import MemoryManager
from hal.core.subagent import SubagentManager
from hal.infra.providers.base import LLMProvider
from hal.session.manager import SessionManager

if TYPE_CHECKING:
    from hal.capabilities.scheduling.cron_service import CronService
    from hal.infra.config.schema import ExecToolConfig


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
        session_manager: SessionManager | None = None,
        memory_manager: MemoryManager | None = None,
    ):
        from hal.infra.config.schema import ExecToolConfig

        self.bus = bus
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.web_search_api_key = web_search_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.cron_service = cron_service
        self.restrict_to_workspace = restrict_to_workspace

        self.memory = memory_manager or MemoryManager(workspace)
        self.context = ContextBuilder(workspace, memory_manager=self.memory)
        self.sessions = session_manager or SessionManager(workspace)
        self.tools = ToolRegistry()
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            web_search_api_key=web_search_api_key,
            exec_config=self.exec_config,
            restrict_to_workspace=restrict_to_workspace,
        )

        self._running = False
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        self.tools.register(FsTool(allowed_dir=allowed_dir))

        self.tools.register(
            ExecTool(
                working_dir=str(self.workspace),
                timeout=self.exec_config.timeout,
                restrict_to_workspace=self.restrict_to_workspace,
            )
        )

        self.tools.register(WebSearchTool(api_key=self.web_search_api_key))
        self.tools.register(WebFetchTool())

        message_tool = MessageTool(send_callback=self.bus.publish_outbound)
        self.tools.register(message_tool)

        spawn_tool = SpawnTool(manager=self.subagents)
        self.tools.register(spawn_tool)

        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))

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
        if msg.channel == "system":
            return await self._process_system_message(msg)
        return await self.process_collab(msg)

    # ------------------------------------------------------------------
    # Execution modes
    # ------------------------------------------------------------------

    async def process_collab(self, msg: InboundMessage) -> OutboundMessage | None:
        """
        COLLAB mode: real-time user conversation.

        Low latency, standard tool loop, records episode after completion.
        """
        start_time = time.monotonic()

        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info(f"[collab] {msg.channel}:{msg.sender_id}: {preview}")

        session = self.sessions.get_or_create(msg.session_key)
        self._update_tool_contexts(msg.channel, msg.chat_id)

        messages = self.context.build_messages(
            history=session.get_history(),
            current_message=msg.content,
            media=msg.media if msg.media else None,
            channel=msg.channel,
            chat_id=msg.chat_id,
            mode=ExecutionMode.COLLAB,
        )

        final_content, tools_used, injected = await self._execute_loop(
            messages, self.max_iterations, session_key=msg.session_key
        )

        if final_content is None:
            final_content = "I've completed processing but have no response to give."

        # Save to session (include any mid-loop injected messages)
        session.add_message("user", msg.content)
        for injected_msg in injected:
            session.add_message("user", injected_msg.content)
        session.add_message("assistant", final_content)
        self.sessions.save(session)

        # Record episode
        duration = time.monotonic() - start_time
        self.memory.record_interaction(
            channel=msg.channel,
            user_request=msg.content,
            agent_response=final_content,
            tools_used=tools_used,
            duration_seconds=duration,
        )

        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info(f"[collab] response: {preview}")

        return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=final_content)

    async def process_operator(
        self,
        prompt: str,
        channel: str = "cli",
        chat_id: str = "direct",
        session_key: str | None = None,
    ) -> str:
        """
        OPERATOR mode: scheduled monitoring.

        Used by cron jobs and heartbeat. Higher signal-to-noise — only
        produces output when there's something actionable.
        """
        start_time = time.monotonic()
        s_key = session_key or f"{channel}:{chat_id}"

        logger.info(f"[operator] {s_key}: {prompt[:60]}...")

        session = self.sessions.get_or_create(s_key)
        self._update_tool_contexts(channel, chat_id)

        messages = self.context.build_messages(
            history=session.get_history(),
            current_message=prompt,
            channel=channel,
            chat_id=chat_id,
            mode=ExecutionMode.OPERATOR,
        )

        # Operator mode uses fewer iterations
        max_iter = min(self.max_iterations, 10)
        final_content, tools_used, _ = await self._execute_loop(
            messages, max_iter, session_key=s_key
        )

        if final_content is None:
            final_content = "Monitoring complete. Nothing to report."

        session.add_message("user", prompt)
        session.add_message("assistant", final_content)
        self.sessions.save(session)

        duration = time.monotonic() - start_time
        self.memory.record_interaction(
            channel="operator",
            user_request=prompt,
            agent_response=final_content,
            tools_used=tools_used,
            duration_seconds=duration,
        )

        return final_content

    # ------------------------------------------------------------------
    # System message handling (subagent announces)
    # ------------------------------------------------------------------

    async def _process_system_message(self, msg: InboundMessage) -> OutboundMessage | None:
        """Process a system message (e.g., subagent result announce)."""
        logger.info(f"[system] from {msg.sender_id}")

        if ":" in msg.chat_id:
            parts = msg.chat_id.split(":", 1)
            origin_channel, origin_chat_id = parts[0], parts[1]
        else:
            origin_channel, origin_chat_id = "cli", msg.chat_id

        session_key = f"{origin_channel}:{origin_chat_id}"
        session = self.sessions.get_or_create(session_key)
        self._update_tool_contexts(origin_channel, origin_chat_id)

        messages = self.context.build_messages(
            history=session.get_history(),
            current_message=msg.content,
            channel=origin_channel,
            chat_id=origin_chat_id,
        )

        final_content, _, _ = await self._execute_loop(
            messages, self.max_iterations, session_key=session_key
        )

        if final_content is None:
            final_content = "Background task completed."

        session.add_message("user", f"[System: {msg.sender_id}] {msg.content}")
        session.add_message("assistant", final_content)
        self.sessions.save(session)

        return OutboundMessage(
            channel=origin_channel, chat_id=origin_chat_id, content=final_content
        )

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
    # Core tool loop (shared by all modes)
    # ------------------------------------------------------------------

    async def _execute_loop(
        self,
        messages: list[dict[str, Any]],
        max_iterations: int,
        session_key: str | None = None,
    ) -> tuple[str | None, list[str], list[InboundMessage]]:
        """
        Run the LLM tool-calling loop.

        If *session_key* is provided, new inbound messages for the same session
        are drained from the bus between iterations and injected as user
        messages — the LLM sees them on the next turn without interrupting
        the current execution.

        Returns:
            Tuple of (final_content, tools_used, injected_messages).
        """
        iteration = 0
        final_content: str | None = None
        tools_used: list[str] = []
        injected: list[InboundMessage] = []

        while iteration < max_iterations:
            iteration += 1

            # Inject any messages that arrived mid-execution
            if session_key:
                for pending in self._drain_pending_for_session(session_key):
                    prefixed = f"[User follow-up while you are working] {pending.content}"
                    messages.append({"role": "user", "content": prefixed})
                    injected.append(pending)
                    logger.info(f"[inject] mid-loop message from {pending.sender_id}")

            response = await self.provider.chat(
                messages=messages, tools=self.tools.get_definitions(), model=self.model
            )

            if response.has_tool_calls:
                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts
                )

                for tool_call in response.tool_calls:
                    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                    logger.info(f"Tool call: {tool_call.name}({args_str[:200]})")
                    if tool_call.name not in tools_used:
                        tools_used.append(tool_call.name)

                results = await asyncio.gather(
                    *(self.tools.execute(tc.name, tc.arguments) for tc in response.tool_calls)
                )

                for tool_call, result in zip(response.tool_calls, results):
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                final_content = response.content
                break

        return final_content, tools_used, injected

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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


# Backward compatibility alias
AgentLoop = AgentEngine
