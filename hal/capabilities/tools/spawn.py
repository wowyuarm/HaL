"""Spawn tool for delegating tasks to subagents."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from hal.bus.events import OutboundMessage
from hal.capabilities.tools.base import Tool
from hal.core.ports import SubagentExecutionResult, SubagentPort

# Interval (seconds) between progress messages for sync spawn.
_PROGRESS_INTERVAL = 30


class SpawnTool(Tool):
    """
    Tool to delegate a task to a subagent.

    By default the subagent runs synchronously — the main agent's loop
    awaits completion and receives the result as a normal tool_result.
    Set ``background=true`` for long-running tasks where the main agent
    should respond to the user immediately.
    """

    def __init__(
        self,
        manager: SubagentPort,
        send_callback: Callable[[OutboundMessage], Awaitable[None]] | None = None,
    ):
        self._manager = manager
        self._send_callback = send_callback
        self._origin_channel = "cli"
        self._origin_chat_id = "direct"

    def set_context(self, channel: str, chat_id: str) -> None:
        """Set the origin context for background subagent announcements."""
        self._origin_channel = channel
        self._origin_chat_id = chat_id

    @property
    def name(self) -> str:
        return "spawn"

    @property
    def description(self) -> str:
        return (
            "Delegate a task to a subagent. The subagent has its own tools "
            "(file, exec, web) and will complete the task independently. "
            "By default it runs synchronously and returns the result directly. "
            "Set background=true for long-running tasks."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The task for the subagent to complete",
                },
                "label": {
                    "type": "string",
                    "description": "Optional short label for the task (for display)",
                },
                "background": {
                    "type": "boolean",
                    "description": (
                        "Run in background (fire-and-forget). "
                        "Default false — waits and returns result directly."
                    ),
                    "default": False,
                },
            },
            "required": ["task"],
        }

    async def execute(
        self,
        task: str,
        label: str | None = None,
        background: bool = False,
        **kwargs: Any,
    ) -> str:
        """Delegate a task to a subagent."""
        if background:
            return await self._manager.spawn_background(
                task=task,
                label=label,
            )

        display_label = label or task[:40]

        # Run with periodic progress reporting for sync execution.
        progress_task: asyncio.Task | None = None
        if self._send_callback:
            progress_task = asyncio.create_task(self._report_progress(display_label))

        try:
            details = await self._manager.run_with_details(task=task, label=label)
            return self._format_result(details)
        finally:
            if progress_task:
                progress_task.cancel()
                try:
                    await progress_task
                except asyncio.CancelledError:
                    pass

    async def _report_progress(self, label: str) -> None:
        """Periodically send progress messages to the user."""
        elapsed = 0
        try:
            while True:
                await asyncio.sleep(_PROGRESS_INTERVAL)
                elapsed += _PROGRESS_INTERVAL
                count = self._manager.get_running_count()
                iterations = self._manager.get_last_iteration()
                msg = (
                    f"[Subagent: {label}] still working... "
                    f"({elapsed}s elapsed, {iterations} tool calls"
                    f"{f', {count} background tasks' if count else ''})"
                )
                logger.debug(f"[progress] {msg}")
                if self._send_callback:
                    await self._send_callback(
                        OutboundMessage(
                            channel=self._origin_channel,
                            chat_id=self._origin_chat_id,
                            content=msg,
                        )
                    )
        except asyncio.CancelledError:
            raise

    @staticmethod
    def _format_result(details: SubagentExecutionResult) -> str:
        """Encode subagent detail metadata into the tool result payload."""
        lines = [details.content]
        if details.record_id:
            lines.append(f"[Subagent Record ID] {details.record_id}")
        if details.status:
            lines.append(f"[Subagent Status] {details.status}")
        if details.artifact_path:
            lines.append(f"[Subagent Artifact] {details.artifact_path}")
        if details.log_path and details.log_path != details.artifact_path:
            lines.append(f"[Subagent Log] {details.log_path}")
        if details.total_tokens:
            lines.append(f"[Subagent Total Tokens] {details.total_tokens}")
        if details.tools_used:
            lines.append(
                f"[Subagent Tools Used] {json.dumps(details.tools_used, ensure_ascii=False)}"
            )
        if details.tool_call_counts:
            lines.append(
                f"[Subagent Tool Counts] {json.dumps(details.tool_call_counts, ensure_ascii=False)}"
            )
        lines.append(
            f"[Subagent Has Side Effects] {'true' if details.has_side_effects else 'false'}"
        )
        if details.files_modified:
            lines.append(
                f"[Subagent Files Modified] {json.dumps(details.files_modified, ensure_ascii=False)}"
            )
        if details.commands_run:
            lines.append(
                f"[Subagent Commands Run] {json.dumps(details.commands_run, ensure_ascii=False)}"
            )
        if details.tool_errors:
            lines.append(
                f"[Subagent Tool Errors] {json.dumps(details.tool_errors, ensure_ascii=False)}"
            )
        if details.missing_artifacts:
            lines.append(
                "[Subagent Missing Artifacts] "
                + json.dumps([str(p) for p in details.missing_artifacts], ensure_ascii=False)
            )
        return "\n\n".join(lines)
