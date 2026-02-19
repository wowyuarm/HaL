"""Subagent manager for delegated task execution."""

from __future__ import annotations

import asyncio
import platform
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from hal.core.context.builder import _MODE_DIRECTIVES, ExecutionMode
from hal.core.runtime.loop import LoopMetadata, run_tool_loop
from hal.core.runtime.tool_factory import create_tools
from hal.infra.providers.base import LLMProvider

if TYPE_CHECKING:
    from hal.capabilities.tools.registry import ToolRegistry
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
    - **Background**: runs in parallel, results are collected by the engine's
      ``_execute_loop`` before it finishes, so the main agent sees all
      results in the same turn without extra LLM round-trips.
    """

    def __init__(
        self,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        web_search_api_key: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
        restrict_to_workspace: bool = False,
    ):
        from hal.infra.config.schema import ExecToolConfig

        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.web_search_api_key = web_search_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.restrict_to_workspace = restrict_to_workspace
        # task_id -> (asyncio.Task, label)
        self._running_tasks: dict[str, tuple[asyncio.Task[str], str]] = {}
        # Track iteration count for the currently executing sync subagent
        self._current_iteration = 0

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
    ) -> str:
        """
        Spawn a subagent in the background (parallel execution).

        The result is collected by ``await_pending()`` in the engine's
        ``_execute_loop`` before the loop finishes, so the main agent
        sees all background results in the same conversation turn.
        """
        task_id = str(uuid.uuid4())[:8]
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")

        bg_task = asyncio.create_task(self._execute_subagent(task_id, task))
        self._running_tasks[task_id] = (bg_task, display_label)

        logger.info(f"Spawned background subagent [{task_id}]: {display_label}")
        return (
            f"Background subagent [{display_label}] started (id: {task_id}). "
            f"Results will be delivered when all background tasks complete."
        )

    async def await_pending(self) -> list[tuple[str, str]]:
        """
        Await all pending background subagents and return their results.

        Returns a list of ``(label, result)`` tuples. Clears the pending
        task set after collection. Safe to call when no tasks are pending
        (returns empty list).
        """
        if not self._running_tasks:
            return []

        results: list[tuple[str, str]] = []
        for task_id, (task, label) in list(self._running_tasks.items()):
            try:
                result = await task
                logger.info(f"Subagent [{task_id}] ({label}) completed")
                results.append((label, result))
            except Exception as e:
                logger.error(f"Subagent [{task_id}] ({label}) failed: {e}")
                results.append((label, f"Error: {e}"))

        self._running_tasks.clear()
        return results

    # ------------------------------------------------------------------
    # Internal execution
    # ------------------------------------------------------------------

    async def _execute_subagent(self, task_id: str, task: str) -> str:
        """Run the subagent loop and return the final result string."""
        tools = self._build_tools()
        system_prompt = self._build_system_prompt()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task},
        ]

        max_iterations = 50
        self._current_iteration = 0

        hooks = _SubagentLoopHooks(self, task_id)

        final_content, _meta = await run_tool_loop(
            provider=self.provider,
            model=self.model,
            tools=tools,
            messages=messages,
            max_iterations=max_iterations,
            hooks=hooks,
        )

        if final_content is None:
            final_content = "Task completed but no summary was generated."

        logger.info(f"Subagent [{task_id}] completed")
        return final_content

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_tools(self) -> "ToolRegistry":
        """Build an isolated tool registry for a subagent."""
        return create_tools(
            workspace=self.workspace,
            exec_config=self.exec_config,
            restrict_to_workspace=self.restrict_to_workspace,
            web_search_api_key=self.web_search_api_key,
        )

    def _build_system_prompt(self) -> str:
        """Build a focused, task-agnostic system prompt for the subagent.

        The task itself is delivered as the user message, keeping the system
        prompt stable (and potentially cacheable across subagent invocations).

        Includes:
        - Role and behavioral rules
        - Tool usage guide (subset available to subagent)
        - Long-term memory (MEMORY.md) for user preferences and project context
        - Environment basics (time, platform, workspace)
        """
        mode_directive = _MODE_DIRECTIVES[ExecutionMode.ASYNC]
        workspace_path = str(self.workspace.expanduser().resolve())

        system = platform.system()
        runtime = (
            f"{'macOS' if system == 'Darwin' else system} "
            f"{platform.machine()}, Python {platform.python_version()}"
        )
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")

        parts: list[str] = []

        # Role + mode
        parts.append(f"""# Subagent

You are a focused task executor working on behalf of the main agent.
Your result will be reported back — you do not interact with the user directly.

{mode_directive}""")

        # Rules
        parts.append("""\
## Rules
- Complete only the assigned task. Do not take on side tasks.
- Be thorough in execution, concise in your final report.
- If the task is ambiguous, make reasonable assumptions and state them.""")

        # Tool usage guide (only the tools subagent actually has)
        parts.append(f"""\
## Tools

### fs — File Operations
Unified file tool with four actions:
```
fs(action="read", path="file.txt")
fs(action="write", path="file.txt", content="...")
fs(action="edit", path="file.txt", old_text="...", new_text="...")
fs(action="list", path=".")
```

### exec — Shell Execution
Execute shell commands. Output truncated at 10K chars.
```
exec(command="ls -la", working_dir="/path")
```

### web_search — Web Search
```
web_search(query="latest news", count=5)
```

### web_fetch — Fetch Web Page
Extract main content from a URL as markdown.
```
web_fetch(url="https://example.com", extractMode="markdown")
```

## Environment
Platform: {runtime}
Workspace: {workspace_path}
Current time: {now}""")

        return "\n\n".join(parts)

    def get_running_count(self) -> int:
        """Return the number of currently running background subagents."""
        return len(self._running_tasks)

    def get_last_iteration(self) -> int:
        """Return the iteration count of the most recent sync subagent execution."""
        return self._current_iteration


class _SubagentLoopHooks:
    """Loop hooks for subagent execution.

    Tracks iteration count and forces a summary when the loop is exhausted.
    """

    def __init__(self, manager: SubagentManager, task_id: str):
        self._manager = manager
        self._task_id = task_id

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

    async def on_no_tool_calls(
        self,
        messages: list[dict[str, Any]],
        response: Any,
        meta: LoopMetadata,
    ) -> bool:
        return False

    async def on_loop_exhausted(
        self,
        messages: list[dict[str, Any]],
        meta: LoopMetadata,
    ) -> str | None:
        """Force a final summary when max iterations reached."""
        logger.warning(f"Subagent [{self._task_id}] hit max iterations, forcing summary")
        messages.append(
            {
                "role": "user",
                "content": (
                    "You have reached the maximum number of tool iterations. "
                    "Do NOT call any more tools. Provide a structured final "
                    "report:\n"
                    "1. **Completed**: what you accomplished\n"
                    "2. **Incomplete**: what remains unfinished (if any)\n"
                    "3. **Key findings**: important results or data discovered"
                ),
            }
        )
        response = await self._manager.provider.chat(
            messages=messages, tools=[], model=self._manager.model
        )
        return response.content
