"""Spawn tool for delegating tasks to subagents."""

from typing import TYPE_CHECKING, Any

from hal.capabilities.tools.base import Tool

if TYPE_CHECKING:
    from hal.core.subagent import SubagentManager


class SpawnTool(Tool):
    """
    Tool to delegate a task to a subagent.

    By default the subagent runs synchronously — the main agent's loop
    awaits completion and receives the result as a normal tool_result.
    Set ``background=true`` for long-running tasks where the main agent
    should respond to the user immediately.
    """

    def __init__(self, manager: "SubagentManager"):
        self._manager = manager
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
                origin_channel=self._origin_channel,
                origin_chat_id=self._origin_chat_id,
            )
        return await self._manager.run(task=task, label=label)
