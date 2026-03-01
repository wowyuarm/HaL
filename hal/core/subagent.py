"""Subagent manager for delegated task execution."""

from __future__ import annotations

import asyncio
import json
import platform
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from hal.core.context.builder import _MODE_DIRECTIVES, ExecutionMode
from hal.core.ports import SubagentExecutionResult
from hal.core.runtime.loop import LoopMetadata, run_tool_loop
from hal.core.runtime.tool_factory import create_tools
from hal.infra.providers.base import LLMProvider

if TYPE_CHECKING:
    from hal.capabilities.tools.registry import ToolRegistry
    from hal.infra.config.schema import ExecToolConfig, WebFetchConfig, WebSearchConfig

_ARTIFACT_PATH_RE = re.compile(r"(/[^`'\"<>\s)]+\.md)\b")
_PARTIAL_INDICATOR_RE = re.compile(
    r"\b(could not|couldn't|unable|not able|hard blocker|incomplete|remaining|blocked)\b",
    re.IGNORECASE,
)


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
        max_iterations: int = 20,
        web_search_config: "WebSearchConfig | None" = None,
        web_fetch_config: "WebFetchConfig | None" = None,
    ):
        from hal.infra.config.schema import ExecToolConfig

        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.web_search_api_key = web_search_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.restrict_to_workspace = restrict_to_workspace
        self.max_iterations = max_iterations
        self._web_search_config = web_search_config
        self._web_fetch_config = web_fetch_config
        # task_id -> (asyncio.Task, label)
        self._running_tasks: dict[str, tuple[asyncio.Task[SubagentExecutionResult], str]] = {}
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

        result = await self._execute_subagent(task_id, task, label=label)
        return result.content

    async def run_with_details(
        self,
        task: str,
        label: str | None = None,
    ) -> "SubagentExecutionResult":
        """Execute a subagent synchronously and return result metadata."""
        task_id = str(uuid.uuid4())[:8]
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")
        logger.info(f"Subagent [{task_id}] running with details: {display_label}")
        return await self._execute_subagent(task_id, task, label=label)

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

        bg_task = asyncio.create_task(self._execute_subagent(task_id, task, label=label))
        self._running_tasks[task_id] = (bg_task, display_label)

        logger.info(f"Spawned background subagent [{task_id}]: {display_label}")
        return (
            f"Background subagent [{display_label}] started (id: {task_id}). "
            f"Results will be delivered when all background tasks complete."
        )

    async def await_pending(self) -> list[tuple[str, "SubagentExecutionResult"]]:
        """
        Await all pending background subagents and return their results.

        Returns a list of ``(label, result)`` tuples. Clears the pending
        task set after collection. Safe to call when no tasks are pending
        (returns empty list).
        """
        if not self._running_tasks:
            return []

        results: list[tuple[str, SubagentExecutionResult]] = []
        for task_id, (task, label) in list(self._running_tasks.items()):
            try:
                result = await task
                logger.info(f"Subagent [{task_id}] ({label}) completed")
                results.append((label, result))
            except Exception as e:
                logger.error(f"Subagent [{task_id}] ({label}) failed: {e}")
                results.append(
                    (
                        label,
                        SubagentExecutionResult(
                            content=f"Error: {e}",
                            artifact_path=None,
                            total_tokens=0,
                            status="failed",
                        ),
                    )
                )

        self._running_tasks.clear()
        return results

    # ------------------------------------------------------------------
    # Internal execution
    # ------------------------------------------------------------------

    async def _execute_subagent(
        self,
        task_id: str,
        task: str,
        label: str | None = None,
    ) -> "SubagentExecutionResult":
        """Run the subagent loop and return the final result string."""
        tools = self._build_tools()
        system_prompt = self._build_system_prompt()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task},
        ]

        max_iterations = self.max_iterations
        self._current_iteration = 0

        hooks = _SubagentLoopHooks(self, task_id)

        final_content, meta = await run_tool_loop(
            provider=self.provider,
            model=self.model,
            tools=tools,
            messages=messages,
            max_iterations=max_iterations,
            hooks=hooks,
        )

        if final_content is None:
            final_content = "Task completed but no summary was generated."

        artifacts, missing_artifacts = self._extract_artifact_paths(final_content)
        tool_errors = self._extract_tool_errors(meta.loop_messages)
        status = self._classify_status(
            final_content=final_content,
            loop_exhausted=hooks.loop_exhausted,
            missing_artifacts=missing_artifacts,
            tool_errors=tool_errors,
        )
        log_path = self._append_execution_log(
            task_id=task_id,
            label=label,
            task=task,
            result=final_content,
            meta=meta,
            artifacts=artifacts,
            status=status,
            missing_artifacts=missing_artifacts,
            tool_errors=tool_errors,
        )
        artifact_path = artifacts[0] if artifacts else log_path
        logger.info(f"Subagent [{task_id}] {status} (log: {log_path})")
        return SubagentExecutionResult(
            content=final_content,
            artifact_path=artifact_path,
            total_tokens=meta.total_usage.get("total_tokens", 0),
            record_id=task_id,
            artifacts=artifacts,
            status=status,
            has_side_effects=meta.has_side_effects,
            tools_used=list(meta.tools_used),
            tool_call_counts=dict(meta.tool_call_counts),
            files_modified=list(meta.files_modified),
            commands_run=list(meta.commands_run),
            tool_errors=tool_errors,
            missing_artifacts=missing_artifacts,
            log_path=log_path,
        )

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
            web_search_config=self._web_search_config,
            web_fetch_config=self._web_fetch_config,
        )

    def _build_system_prompt(self) -> str:
        """Build a focused, task-agnostic system prompt for the subagent.

        The task itself is delivered as the user message, keeping the system
        prompt stable (and potentially cacheable across subagent invocations).

        Includes:
        - Role and behavioral rules
        - Tool usage guide (subset available to subagent)
        - Skills (DeepWiki, etc.)
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
- If the task is ambiguous, make reasonable assumptions and state them.
- For file read/write/edit/list tasks, use fs(action=...) as the primary tool.
- Do not use exec(cat/sed/python read_text) as the primary way to read file contents.
- If exec output shows \"truncated\", switch to fs(action=\"read\", offset=..., limit=...) chunked reads.
- If the same tool error repeats twice, change strategy immediately (different tool or corrected params).
- If the task requires writing deliverables, write early (not only at the final step).
- Before claiming a file is written, verify with fs(action=\"list\") and fs(action=\"read\").
- Never claim \"done\" or \"written\" unless verification succeeded.

## Final Output Contract
Your final response must include these sections:
1. Status: completed | partial | failed
2. Completed: what you finished
3. Incomplete: what remains unfinished
4. Deliverables Verified: file paths + exists=true/false
5. Side Effects: files modified, commands run, web actions
6. Key Findings: important outputs/data""")

        # Tool usage guide (only the tools subagent actually has)
        parts.append("""\
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
```""")

        # Skills
        skills_section = self._build_skills_section()
        if skills_section:
            parts.append(skills_section)

        # Environment
        parts.append(f"""\
## Environment
Platform: {runtime}
Workspace: {workspace_path}
Current time: {now}""")

        return "\n\n".join(parts)

    def _build_skills_section(self) -> str | None:
        """Build the skills section for the subagent system prompt.

        Loads skills that are useful for subagent tasks (e.g., DeepWiki for
        repository research). Skills are loaded with absolute script paths
        so the subagent can execute them directly.
        """
        from hal.capabilities.skills.loader import SkillsLoader

        loader = SkillsLoader(self.workspace)
        parts: list[str] = []

        # DeepWiki — essential for repository research tasks
        deepwiki_content = loader.load_skill("deepwiki")
        if deepwiki_content:
            # Resolve the absolute path to the deepwiki script
            deepwiki_script = self._resolve_skill_script("deepwiki", "scripts/deepwiki.sh")
            if deepwiki_script:
                content = loader._strip_frontmatter(deepwiki_content)
                # Replace relative script paths with absolute paths
                content = content.replace(
                    "scripts/deepwiki.sh",
                    str(deepwiki_script),
                )
                parts.append(f"### Skill: DeepWiki\n\n{content}")

        if not parts:
            return None

        return "## Skills\n\n" + "\n\n---\n\n".join(parts)

    def _resolve_skill_script(self, skill_name: str, relative_path: str) -> Path | None:
        """Resolve the absolute path to a skill's script file.

        Skills are resolved from workspace-only skills.
        """
        workspace_path = self.workspace / "skills" / skill_name / relative_path
        if workspace_path.exists():
            return workspace_path

        return None

    def get_running_count(self) -> int:
        """Return the number of currently running background subagents."""
        return len(self._running_tasks)

    def get_last_iteration(self) -> int:
        """Return the iteration count of the most recent sync subagent execution."""
        return self._current_iteration

    def _append_execution_log(
        self,
        task_id: str,
        label: str | None,
        task: str,
        result: str,
        meta: LoopMetadata,
        artifacts: list[Path],
        status: str,
        missing_artifacts: list[Path],
        tool_errors: list[str],
    ) -> Path | None:
        """Append full subagent execution details to artifacts/subagent/subagent-log.jsonl."""
        try:
            artifact_dir = self.workspace / "artifacts" / "subagent"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            log_path = artifact_dir / "subagent-log.jsonl"
            display_label = label or task[:40] + ("..." if len(task) > 40 else "")
            record = {
                "id": task_id,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "label": display_label,
                "task": task,
                "iterations": meta.iterations,
                "tools_used": meta.tools_used,
                "tool_call_counts": meta.tool_call_counts,
                "has_side_effects": meta.has_side_effects,
                "files_modified": meta.files_modified,
                "commands_run": meta.commands_run,
                "tool_errors": tool_errors,
                "tokens": meta.total_usage.get("total_tokens", 0),
                "result": result,
                "artifacts": [str(path) for path in artifacts],
                "missing_artifacts": [str(path) for path in missing_artifacts],
                "status": status,
            }
            with log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            return log_path
        except Exception as e:
            logger.warning(f"Failed to append subagent execution log: {e}")
            return None

    def _extract_artifact_paths(self, result: str) -> tuple[list[Path], list[Path]]:
        """Extract and validate absolute markdown artifact paths referenced in output."""
        artifacts: list[Path] = []
        missing: list[Path] = []
        seen: set[str] = set()
        for raw_path in _ARTIFACT_PATH_RE.findall(result):
            path = Path(raw_path)
            if not path.is_absolute():
                continue
            normalized = str(path)
            if normalized in seen:
                continue
            seen.add(normalized)
            if path.exists() and path.is_file():
                artifacts.append(path)
            else:
                missing.append(path)
        return artifacts, missing

    def _extract_tool_errors(self, loop_messages: list[dict[str, Any]]) -> list[str]:
        """Collect unique tool errors from loop messages for observability."""
        errors: list[str] = []
        seen: set[str] = set()
        for msg in loop_messages:
            if not isinstance(msg, dict) or msg.get("role") != "tool":
                continue
            content = str(msg.get("content", "")).strip()
            if not content.startswith("Error"):
                continue
            name = str(msg.get("name") or "tool")
            summary = content.splitlines()[0][:240]
            item = f"{name}: {summary}"
            if item in seen:
                continue
            seen.add(item)
            errors.append(item)
        return errors

    def _classify_status(
        self,
        *,
        final_content: str,
        loop_exhausted: bool,
        missing_artifacts: list[Path],
        tool_errors: list[str],
    ) -> str:
        """Classify execution status for downstream routing and logging."""
        text = final_content.strip()
        lowered = text.lower()

        if lowered.startswith("error calling llm:") or lowered.startswith("error:"):
            return "failed"
        if loop_exhausted:
            return "exhausted"
        if missing_artifacts:
            return "partial"
        if _PARTIAL_INDICATOR_RE.search(text):
            return "partial"
        if tool_errors and _PARTIAL_INDICATOR_RE.search("\n".join(tool_errors)):
            return "partial"
        return "completed"


class _SubagentLoopHooks:
    """Loop hooks for subagent execution.

    Tracks iteration count and forces a summary when the loop is exhausted.
    """

    def __init__(self, manager: SubagentManager, task_id: str):
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
