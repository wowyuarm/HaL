"""AgentEngine — unified execution engine for all interaction modes."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
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

if TYPE_CHECKING:
    from hal.capabilities.scheduling.cron_service import CronService
    from hal.core.memory.search import MemorySearch
    from hal.infra.config.schema import ExecToolConfig


SIDE_EFFECT_TOOLS = {"fs", "exec"}
FS_SIDE_EFFECT_ACTIONS = {"write", "edit"}


@dataclass
class LoopMetadata:
    """Metadata collected during a tool-calling loop execution."""

    iterations: int = 0
    tools_used: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    has_side_effects: bool = False
    loop_messages: list[dict[str, Any]] = field(default_factory=list)

    @property
    def needs_summary(self) -> bool:
        return self.iterations >= 5 or self.has_side_effects


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
        memory_search: "MemorySearch | None" = None,
        auto_inject_top_k: int = 3,
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
        self._summary_model = summary_model
        self._memory_search = memory_search
        self._auto_inject_top_k = auto_inject_top_k
        self._pending_summaries: dict[str, asyncio.Task] = {}

        self.memory = memory_manager or MemoryManager(workspace)
        self.context = ContextBuilder(workspace, memory_manager=self.memory)
        self.tools = ToolRegistry()
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
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

        spawn_tool = SpawnTool(manager=self.subagents, send_callback=self.bus.publish_outbound)
        self.tools.register(spawn_tool)

        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))

        if self._memory_search:
            from hal.capabilities.tools.recall import RecallTool

            self.tools.register(RecallTool(self._memory_search))

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
        return await self.process_collab(msg)

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
        history = self.memory.get_conversation_history(
            channel=msg.channel,
            chat_id=msg.chat_id,
            max_messages=50,
            include_tools=False,
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

        # Record any mid-loop injected messages
        for injected_msg in injected:
            self.memory.record_conversation(
                channel=msg.channel,
                chat_id=msg.chat_id,
                role="user",
                content=injected_msg.content,
            )

        # Trigger async summary if qualifying loop
        if meta.needs_summary:
            self._pending_summaries[msg.session_key] = asyncio.create_task(
                self._generate_summary(meta, final_content, msg.channel, msg.chat_id)
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
        s_key = session_key or f"{channel}:{chat_id}"

        logger.info(f"[operator] {s_key}: {prompt[:60]}...")

        # Record operator prompt
        self.memory.record_conversation(
            channel=channel,
            chat_id=chat_id,
            role="user",
            content=prompt,
        )

        self._update_tool_contexts(channel, chat_id)

        # Get conversation history from log
        history = self.memory.get_conversation_history(
            channel=channel,
            chat_id=chat_id,
            max_messages=50,
            include_tools=False,
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
        )

        # Trigger async summary if qualifying loop (no barrier needed for operator)
        if meta.needs_summary:
            asyncio.create_task(self._generate_summary(meta, final_content, channel, chat_id))

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
    # Core tool loop (shared by all modes)
    # ------------------------------------------------------------------

    async def _execute_loop(
        self,
        messages: list[dict[str, Any]],
        max_iterations: int,
        session_key: str | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
    ) -> tuple[str | None, LoopMetadata, list[InboundMessage]]:
        """
        Run the LLM tool-calling loop.

        If *session_key* is provided, new inbound messages for the same session
        are drained from the bus between iterations and injected as user
        messages — the LLM sees them on the next turn without interrupting
        the current execution.

        Returns:
            Tuple of (final_content, loop_metadata, injected_messages).
        """
        iteration = 0
        final_content: str | None = None
        meta = LoopMetadata()
        injected: list[InboundMessage] = []
        start_idx = len(messages)

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
                    messages,
                    response.content,
                    tool_call_dicts,
                    reasoning_content=response.reasoning_content,
                )

                for tool_call in response.tool_calls:
                    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                    logger.info(f"Tool call: {tool_call.name}({args_str[:200]})")
                    if tool_call.name not in meta.tools_used:
                        meta.tools_used.append(tool_call.name)

                    # Track side effects
                    if tool_call.name == "fs":
                        action = tool_call.arguments.get("action", "")
                        if action in FS_SIDE_EFFECT_ACTIONS:
                            meta.has_side_effects = True
                            path = tool_call.arguments.get("path", "")
                            if path and path not in meta.files_modified:
                                meta.files_modified.append(path)
                    elif tool_call.name == "exec":
                        meta.has_side_effects = True
                        cmd = tool_call.arguments.get("command", "")
                        if cmd:
                            meta.commands_run.append(cmd[:200])

                results = await asyncio.gather(
                    *(self.tools.execute(tc.name, tc.arguments) for tc in response.tool_calls)
                )

                for tool_call, result in zip(response.tool_calls, results):
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )

                    # Record tool call and result
                    if channel and chat_id:
                        # Record tool call (as assistant tool message)
                        self.memory.record_conversation(
                            channel=channel,
                            chat_id=chat_id,
                            role="tool",
                            content=f"Calling {tool_call.name} with arguments: {json.dumps(tool_call.arguments, ensure_ascii=False)}",
                            tool_name=tool_call.name,
                            tool_result=result,
                        )

                        # Persist sync spawn results as user-injection so they
                        # survive include_tools=False in future history rebuilds.
                        if tool_call.name == "spawn":
                            bg = tool_call.arguments.get("background", False)
                            if not bg:
                                label = tool_call.arguments.get(
                                    "label", tool_call.arguments.get("task", "")[:40]
                                )
                                self.memory.record_conversation(
                                    channel=channel,
                                    chat_id=chat_id,
                                    role="user",
                                    content=f"[Subagent Result: {label}]\n\n{result}",
                                    entry_type="injection",
                                )
            else:
                # Before finalizing, collect any pending background subagent results.
                # These are injected as ephemeral context (not recorded to history)
                # so the LLM can produce a unified response.
                pending = await self.subagents.await_pending()
                if pending:
                    # LLM wanted to respond, but subagents are still pending.
                    # Inject their results and let the LLM incorporate them.
                    messages = self.context.add_assistant_message(
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

                        # Persist so future history rebuilds retain the result
                        if channel and chat_id:
                            self.memory.record_conversation(
                                channel=channel,
                                chat_id=chat_id,
                                role="user",
                                content=inject,
                                entry_type="injection",
                            )
                    continue

                final_content = response.content
                break

        meta.iterations = iteration
        meta.loop_messages = messages[start_idx:]

        return final_content, meta, injected

    # ------------------------------------------------------------------
    # Post-loop summary
    # ------------------------------------------------------------------

    async def _generate_summary(
        self,
        meta: LoopMetadata,
        final_content: str,
        channel: str,
        chat_id: str,
    ) -> None:
        """Generate a concise summary of a tool-heavy loop and persist it."""
        try:
            # Build a compact representation of what happened
            parts = [
                "Summarize what was done in this tool-calling session concisely (2-4 sentences)."
            ]
            parts.append(f"\nIterations: {meta.iterations}")
            parts.append(f"Tools used: {', '.join(meta.tools_used)}")
            if meta.files_modified:
                parts.append(f"Files modified: {', '.join(meta.files_modified)}")
            if meta.commands_run:
                parts.append(f"Commands run: {', '.join(meta.commands_run)}")
            parts.append(f"\nFinal response to user:\n{final_content[:500]}")

            # Include a condensed version of loop messages (skip system prompt)
            compact_msgs = []
            for msg in meta.loop_messages:
                role = msg.get("role", "")
                content = str(msg.get("content", ""))[:300]
                compact_msgs.append(f"[{role}] {content}")
            if compact_msgs:
                parts.append("\nLoop messages (truncated):\n" + "\n".join(compact_msgs[:20]))

            prompt = "\n".join(parts)

            response = await self.provider.chat(
                messages=[
                    {
                        "role": "system",
                        "content": "You are a concise summarizer. Output only the summary.",
                    },
                    {"role": "user", "content": prompt},
                ],
                tools=[],
                model=self.model if self._summary_model == "default" else self._summary_model,
            )

            if response.content:
                self.memory.record_conversation(
                    channel=channel,
                    chat_id=chat_id,
                    role="user",
                    content=f"[System Summary]\n{response.content}",
                    entry_type="injection",
                )
                logger.info(f"[summary] recorded for {channel}:{chat_id}")
        except Exception as e:
            logger.warning(f"Failed to generate loop summary: {e}")

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
