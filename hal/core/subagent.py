"""Subagent manager for delegated task execution."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from hal.bus.events import InboundMessage
from hal.bus.queue import MessageBus
from hal.capabilities.tools.exec import ExecTool
from hal.capabilities.tools.fs import FsTool
from hal.capabilities.tools.registry import ToolRegistry
from hal.capabilities.tools.web import WebFetchTool, WebSearchTool
from hal.core.context.builder import _MODE_DIRECTIVES, ExecutionMode
from hal.infra.providers.base import LLMProvider

if TYPE_CHECKING:
    from hal.infra.config.schema import ExecToolConfig


class SubagentManager:
    """
    Manages subagent execution.

    Subagents are lightweight agent instances that handle delegated tasks.
    They share the same LLM provider but have isolated context and a
    focused system prompt.

    Two execution modes:
    - **Synchronous** (default): awaits completion, returns result directly
      as a tool_result within the caller's loop. Prompt-cache friendly.
    - **Background**: fire-and-forget, result announced via the message bus
      as a new inbound message. Use for long-running tasks where the main
      agent should respond to the user immediately.
    """

    def __init__(
        self,
        provider: LLMProvider,
        workspace: Path,
        bus: MessageBus,
        model: str | None = None,
        web_search_api_key: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
        restrict_to_workspace: bool = False,
    ):
        from hal.infra.config.schema import ExecToolConfig

        self.provider = provider
        self.workspace = workspace
        self.bus = bus
        self.model = model or provider.get_default_model()
        self.web_search_api_key = web_search_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.restrict_to_workspace = restrict_to_workspace
        self._running_tasks: dict[str, asyncio.Task[None]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self, task: str, label: str | None = None) -> str:
        """
        Execute a subagent synchronously and return its result.

        The caller's loop awaits this method, so the result flows back as
        a normal tool_result — no bus injection, no context break.
        """
        task_id = str(uuid.uuid4())[:8]
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")
        logger.info(f"Subagent [{task_id}] running: {display_label}")

        return await self._execute_subagent(task_id, task)

    async def spawn_background(
        self,
        task: str,
        label: str | None = None,
        origin_channel: str = "cli",
        origin_chat_id: str = "direct",
    ) -> str:
        """
        Spawn a subagent in the background (fire-and-forget).

        Result will be announced via the message bus when complete.
        Use this only for long-running tasks where the main agent should
        respond to the user immediately rather than wait.
        """
        task_id = str(uuid.uuid4())[:8]
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")

        origin = {"channel": origin_channel, "chat_id": origin_chat_id}

        bg_task = asyncio.create_task(self._run_background(task_id, task, display_label, origin))
        self._running_tasks[task_id] = bg_task
        bg_task.add_done_callback(lambda _: self._running_tasks.pop(task_id, None))

        logger.info(f"Spawned background subagent [{task_id}]: {display_label}")
        return (
            f"Background subagent [{display_label}] started (id: {task_id}). "
            f"I'll notify you when it completes."
        )

    # ------------------------------------------------------------------
    # Internal execution
    # ------------------------------------------------------------------

    async def _execute_subagent(self, task_id: str, task: str) -> str:
        """Run the subagent loop and return the final result string."""
        tools = self._build_tools()
        system_prompt = self._build_subagent_prompt(task)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task},
        ]

        max_iterations = 25
        iteration = 0
        final_result: str | None = None

        while iteration < max_iterations:
            iteration += 1

            response = await self.provider.chat(
                messages=messages,
                tools=tools.get_definitions(),
                model=self.model,
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
                messages.append(
                    {
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": tool_call_dicts,
                    }
                )

                for tool_call in response.tool_calls:
                    logger.debug(f"Subagent [{task_id}] executing: {tool_call.name}")

                results = await asyncio.gather(
                    *(tools.execute(tc.name, tc.arguments) for tc in response.tool_calls)
                )

                for tool_call, result in zip(response.tool_calls, results):
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.name,
                            "content": result,
                        }
                    )
            else:
                final_result = response.content
                break

        if final_result is None:
            # Loop exhausted while still making tool calls.
            # Make one final LLM call without tools to force a summary.
            logger.warning(f"Subagent [{task_id}] hit max iterations, forcing summary")
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "You have reached the maximum number of tool iterations. "
                        "Do NOT call any more tools. Summarize your progress and "
                        "findings so far in a final response."
                    ),
                }
            )
            response = await self.provider.chat(messages=messages, tools=[], model=self.model)
            final_result = response.content or "Task completed but no summary was generated."

        logger.info(f"Subagent [{task_id}] completed")
        return final_result

    async def _run_background(
        self,
        task_id: str,
        task: str,
        label: str,
        origin: dict[str, str],
    ) -> None:
        """Execute a background subagent and announce the result via bus."""
        try:
            result = await self._execute_subagent(task_id, task)
            await self._announce_result(task_id, label, result, origin, "ok")
        except Exception as e:
            error_msg = f"Error: {e}"
            logger.error(f"Subagent [{task_id}] failed: {e}")
            await self._announce_result(task_id, label, error_msg, origin, "error")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_tools(self) -> ToolRegistry:
        """Build an isolated tool registry for a subagent."""
        tools = ToolRegistry()
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        tools.register(FsTool(allowed_dir=allowed_dir))
        tools.register(
            ExecTool(
                working_dir=str(self.workspace),
                timeout=self.exec_config.timeout,
                restrict_to_workspace=self.restrict_to_workspace,
            )
        )
        tools.register(WebSearchTool(api_key=self.web_search_api_key))
        tools.register(WebFetchTool())
        return tools

    async def _announce_result(
        self,
        task_id: str,
        label: str,
        result: str,
        origin: dict[str, str],
        status: str,
    ) -> None:
        """Announce a background subagent result via the message bus."""
        status_text = "completed successfully" if status == "ok" else "failed"

        announce_content = f"""[Subagent '{label}' {status_text}]

Result:
{result}

This is a report from a background subagent you delegated. \
Review the result and decide your next step: \
respond to the user, continue your own reasoning, or delegate further work."""

        msg = InboundMessage(
            channel="system",
            sender_id="subagent",
            chat_id=f"{origin['channel']}:{origin['chat_id']}",
            content=announce_content,
        )

        await self.bus.publish_inbound(msg)
        logger.debug(
            f"Subagent [{task_id}] announced result to {origin['channel']}:{origin['chat_id']}"
        )

    def _build_subagent_prompt(self, task: str) -> str:
        """Build a focused system prompt for the subagent."""
        mode_directive = _MODE_DIRECTIVES[ExecutionMode.ASYNC]
        return f"""# Subagent

{mode_directive}

## Your Task
{task}

## Rules
1. Stay focused - complete only the assigned task, nothing else
2. Your final response will be reported back to the main agent
3. Do not initiate conversations or take on side tasks
4. Be concise but informative in your findings

## What You Can Do
- Read and write files in the workspace
- Execute shell commands
- Search the web and fetch web pages
- Complete the task thoroughly

## What You Cannot Do
- Send messages directly to users (no message tool available)
- Spawn other subagents
- Access the main agent's conversation history

## Workspace
Your workspace is at: {self.workspace}

When you have completed the task, provide a clear summary of your findings or actions."""

    def get_running_count(self) -> int:
        """Return the number of currently running background subagents."""
        return len(self._running_tasks)
