"""Subagent manager for delegated task execution."""

from __future__ import annotations

import asyncio
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from hal.bus.events import SubagentCompleteEvent
from hal.core.ports import SubagentExecutionResult
from hal.core.runtime.loop import run_tool_loop
from hal.core.runtime.tool_factory import create_tools
from hal.infra.providers.base import LLMProvider

from .hooks import SubagentLoopHooks
from .prompt import build_skills_section, build_system_prompt, resolve_skill_script
from .results import (
    append_execution_log,
    classify_status,
    extract_artifact_paths,
    extract_tool_errors,
)

if TYPE_CHECKING:
    from hal.bus.queue import MessageBus
    from hal.capabilities.tools.registry import ToolRegistry
    from hal.infra.config.schema import ExecToolConfig, WebFetchConfig, WebSearchConfig


@dataclass(slots=True)
class _BackgroundExecutionContext:
    channel: str | None = None
    chat_id: str | None = None
    session_key: str | None = None


_COMPLETED_RESULTS_MAX = 256


class SubagentManager:
    """Manages synchronous and background subagent execution."""

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
        bus: "MessageBus | None" = None,
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
        self._bus = bus

        # task_id -> (task, display_label, context)
        self._running_tasks: dict[
            str,
            tuple[asyncio.Task[SubagentExecutionResult], str, _BackgroundExecutionContext],
        ] = {}
        self._completed_results: deque[tuple[str, SubagentExecutionResult]] = deque(
            maxlen=_COMPLETED_RESULTS_MAX
        )

        # Track iteration count for the currently executing sync subagent.
        self._current_iteration = 0

    async def run(self, task: str, label: str | None = None) -> str:
        """Execute a subagent synchronously and return its content."""
        task_id = str(uuid.uuid4())[:8]
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")
        logger.info(f"Subagent [{task_id}] running: {display_label}")

        result = await self._execute_subagent(task_id, task, label=label)
        return result.content

    async def run_with_details(
        self,
        task: str,
        label: str | None = None,
    ) -> SubagentExecutionResult:
        """Execute a subagent synchronously and return result metadata."""
        task_id = str(uuid.uuid4())[:8]
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")
        logger.info(f"Subagent [{task_id}] running with details: {display_label}")
        return await self._execute_subagent(task_id, task, label=label)

    async def spawn_background(
        self,
        task: str,
        label: str | None = None,
        *,
        channel: str | None = None,
        chat_id: str | None = None,
        session_key: str | None = None,
    ) -> str:
        """Spawn a subagent in the background and report completion via bus events."""
        task_id = str(uuid.uuid4())[:8]
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")
        context = _BackgroundExecutionContext(
            channel=channel,
            chat_id=chat_id,
            session_key=session_key,
        )

        bg_task = asyncio.create_task(
            self._execute_background_subagent(
                task_id=task_id, task=task, label=label, context=context
            )
        )
        self._running_tasks[task_id] = (bg_task, display_label, context)

        logger.info(f"Spawned background subagent [{task_id}]: {display_label}")
        return (
            f"Background subagent [{display_label}] started (id: {task_id}). "
            "Continue other work now; do not wait. "
            "Results will be delivered as they complete."
        )

    async def await_pending(self) -> list[tuple[str, SubagentExecutionResult]]:
        """Await currently running background tasks and return collected results."""
        if self._running_tasks:
            running = [task for task, _, _ in self._running_tasks.values()]
            await asyncio.gather(*running, return_exceptions=True)

        if not self._completed_results:
            return []

        results = list(self._completed_results)
        self._completed_results.clear()
        return results

    async def _execute_background_subagent(
        self,
        *,
        task_id: str,
        task: str,
        label: str | None,
        context: _BackgroundExecutionContext,
    ) -> SubagentExecutionResult:
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")
        try:
            result = await self._execute_subagent(task_id, task, label=label)
            logger.info(f"Subagent [{task_id}] ({display_label}) completed")
        except Exception as e:
            logger.error(f"Subagent [{task_id}] ({display_label}) failed: {e}")
            result = SubagentExecutionResult(
                content=f"Error: {e}",
                artifact_path=None,
                total_tokens=0,
                status="failed",
            )

        self._completed_results.append((display_label, result))
        self._running_tasks.pop(task_id, None)
        self._emit_background_complete_event(display_label, result, context)
        return result

    async def _execute_subagent(
        self,
        task_id: str,
        task: str,
        label: str | None = None,
    ) -> SubagentExecutionResult:
        """Run the subagent loop and return structured output metadata."""
        tools = self._build_tools()
        system_prompt = self._build_system_prompt()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task},
        ]

        self._current_iteration = 0
        hooks = SubagentLoopHooks(self, task_id)

        final_content, meta = await run_tool_loop(
            provider=self.provider,
            model=self.model,
            tools=tools,
            messages=messages,
            max_iterations=self.max_iterations,
            hooks=hooks,
        )

        if final_content is None:
            final_content = "Task completed but no summary was generated."

        artifacts, missing_artifacts = extract_artifact_paths(final_content)
        tool_errors = extract_tool_errors(meta.loop_messages)
        status = classify_status(
            final_content=final_content,
            loop_exhausted=hooks.loop_exhausted,
            missing_artifacts=missing_artifacts,
            tool_errors=tool_errors,
        )
        log_path = append_execution_log(
            workspace=self.workspace,
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
        """Build focused subagent system prompt."""
        return build_system_prompt(self.workspace, self._build_skills_section())

    def _build_skills_section(self) -> str | None:
        """Build optional skills section for subagent prompt."""
        return build_skills_section(self.workspace)

    def _resolve_skill_script(self, skill_name: str, relative_path: str) -> Path | None:
        """Resolve a workspace skill script path."""
        return resolve_skill_script(self.workspace, skill_name, relative_path)

    def get_running_count(self) -> int:
        """Return number of running background subagents."""
        return len(self._running_tasks)

    def get_last_iteration(self) -> int:
        """Return iteration count of the most recent sync subagent execution."""
        return self._current_iteration

    def _emit_background_complete_event(
        self,
        label: str,
        result: SubagentExecutionResult,
        context: _BackgroundExecutionContext,
    ) -> None:
        """Emit SubagentCompleteEvent for background tasks (best-effort)."""
        if not self._bus:
            return

        self._bus.emit_nowait(
            SubagentCompleteEvent(
                label=label,
                status=result.status,
                content=result.content,
                background=True,
                messages=[],
                channel=context.channel,
                chat_id=context.chat_id,
                session_key=context.session_key,
                record_id=result.record_id or None,
                artifact_path=str(result.artifact_path) if result.artifact_path else None,
                total_tokens=result.total_tokens,
                tools_used=list(result.tools_used),
                tool_call_counts=dict(result.tool_call_counts),
                has_side_effects=result.has_side_effects,
                files_modified=list(result.files_modified),
                commands_run=list(result.commands_run),
                tool_errors=list(result.tool_errors),
                missing_artifacts=[str(p) for p in result.missing_artifacts],
            )
        )
