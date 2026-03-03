"""Loop hooks for subagent execution."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from hal.core.runtime.loop import LoopMetadata

if TYPE_CHECKING:
    from .manager import SubagentManager


class SubagentLoopHooks:
    """Tracks iteration count and injects error-recovery guidance."""

    def __init__(self, manager: "SubagentManager", task_id: str):
        self._manager = manager
        self._task_id = task_id
        self.loop_exhausted = False
        self._last_error_signature = ""
        self._repeat_error_count = 0
        self.error_recovery_injections = 0

    def before_llm_call(self, messages: list[dict[str, Any]], meta: LoopMetadata) -> None:
        self._manager._current_iteration = meta.iterations

    def on_tool_result(
        self,
        tool_name: str,
        tool_id: str,
        arguments: dict[str, Any],
        result: str,
        messages: list[dict[str, Any]],
        meta: LoopMetadata,
    ) -> None:
        logger.debug(f"Subagent [{self._task_id}] executed: {tool_name}")

        content = str(result).strip()
        if not content.startswith("Error"):
            self._last_error_signature = ""
            self._repeat_error_count = 0
            return

        summary = self._summarize_tool_error(content)
        signature = f"{tool_name}:{summary}"
        if signature == self._last_error_signature:
            self._repeat_error_count += 1
        else:
            self._last_error_signature = signature
            self._repeat_error_count = 1

        if self._repeat_error_count < 2:
            return

        self._last_error_signature = ""
        self._repeat_error_count = 0
        self.error_recovery_injections += 1
        logger.warning(
            f"Subagent [{self._task_id}] repeated tool error ({signature}); injecting strategy shift"
        )
        messages.append(
            {
                "role": "user",
                "content": (
                    "You repeated the same tool error twice. Change strategy now. "
                    "Do NOT call the same tool with the same argument shape again. "
                    "For file tasks, use fs(action=read/write/edit/list) instead of exec(cat/sed). "
                    "If command output was truncated, use fs(read, offset, limit) to read in chunks. "
                    "Briefly explain your new plan, then continue with corrected tool calls."
                ),
            }
        )

    async def on_no_tool_calls(
        self,
        messages: list[dict[str, Any]],
        response: Any,
        meta: LoopMetadata,
    ) -> bool:
        return False

    async def on_tool_calls_start(
        self,
        tool_calls: list[Any],
        assistant_content: str | None,
        meta: LoopMetadata,
    ) -> None:
        pass

    async def on_loop_exhausted(
        self,
        messages: list[dict[str, Any]],
        meta: LoopMetadata,
    ) -> str | None:
        """Force a final summary when max iterations reached."""
        self.loop_exhausted = True
        logger.warning(f"Subagent [{self._task_id}] hit max iterations, forcing summary")
        messages.append(
            {
                "role": "user",
                "content": (
                    "You have reached the maximum number of tool iterations. "
                    "Do NOT call any more tools. Provide a structured final report with exactly "
                    "these sections:\n"
                    "1. Status: completed | partial | failed\n"
                    "2. Completed: what you accomplished\n"
                    "3. Incomplete: what remains unfinished (if any)\n"
                    "4. Deliverables Verified: for each file path, include exists=true/false\n"
                    "5. Side Effects: files modified, commands run, network actions\n"
                    "6. Key Findings: important results or data discovered"
                ),
            }
        )
        response = await self._manager.provider.chat(
            messages=messages, tools=[], model=self._manager.model
        )
        return response.content

    @staticmethod
    def _summarize_tool_error(result: str) -> str:
        """Normalize tool error text for duplicate-detection."""
        first_line = result.splitlines()[0].strip()
        return first_line[:200]
