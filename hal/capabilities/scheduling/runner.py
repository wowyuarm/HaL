"""Isolated cron-agent runner."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from hal.capabilities.scheduling.cron_log import CronLog
from hal.capabilities.scheduling.types import CronJob
from hal.core.memory.daily_log import LogEntry
from hal.core.runtime.loop import LoopMetadata, run_tool_loop
from hal.core.runtime.tool_factory import create_tools
from hal.infra.providers.base import LLMProvider

if TYPE_CHECKING:
    from hal.capabilities.tools.registry import ToolRegistry
    from hal.infra.config.schema import ExecToolConfig, WebFetchConfig, WebSearchConfig


class CronAgentRunner:
    """Executes a cron job as an isolated agent with per-job context and logging."""

    def __init__(
        self,
        *,
        cron_dir: Path,
        provider: LLMProvider,
        model: str,
        workspace: Path,
        exec_config: "ExecToolConfig | None" = None,
        restrict_to_workspace: bool = False,
        web_search_api_key: str | None = None,
        summary_window: int = 5,
        max_iterations: int = 10,
        web_search_config: "WebSearchConfig | None" = None,
        web_fetch_config: "WebFetchConfig | None" = None,
    ):
        self.cron_dir = cron_dir
        self.provider = provider
        self.model = model
        self.workspace = workspace
        self.exec_config = exec_config
        self.restrict_to_workspace = restrict_to_workspace
        self.web_search_api_key = web_search_api_key
        self.summary_window = max(1, summary_window)
        self.max_iterations = max(1, max_iterations)
        self._web_search_config = web_search_config
        self._web_fetch_config = web_fetch_config
        self._logs: dict[str, CronLog] = {}

    async def run(self, job: CronJob, prompt: str) -> tuple[str | None, LoopMetadata] | None:
        """Execute a cron job with isolated context."""
        context_content = self._read_context(job.id)
        if context_content is None:
            return None

        log = self.get_log(job.id)
        log.append(
            _make_entry(
                chat_id=job.id,
                role="user",
                content=prompt,
                origin="cron",
            )
        )

        summaries = log.get_recent_summaries(self._summary_window_for(job))
        system_prompt = self._build_system_prompt(
            job=job, context_content=context_content, summaries=summaries
        )
        tools = self._build_tools(job)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        hooks = _CronLoopHooks(log=log, provider=self.provider, model=self.model, job_id=job.id)
        final_content, meta = await run_tool_loop(
            provider=self.provider,
            model=self.model,
            tools=tools,
            messages=messages,
            max_iterations=self.max_iterations,
            hooks=hooks,
        )

        if final_content is None:
            final_content = "Monitoring complete. Nothing to report."

        log.append(
            _make_entry(
                chat_id=job.id,
                role="assistant",
                content=final_content,
                origin="cron",
            )
        )

        return final_content, meta

    def get_log(self, job_id: str) -> CronLog:
        """Get or create the per-job log handle."""
        if job_id not in self._logs:
            self._logs[job_id] = CronLog(self.cron_dir / job_id / "log.jsonl")
        return self._logs[job_id]

    def _read_context(self, job_id: str) -> str | None:
        context_path = self.cron_dir / job_id / "context.md"
        if not context_path.exists():
            return None
        try:
            return context_path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning(f"Failed to read cron context {context_path}: {exc}")
            return None

    def _summary_window_for(self, job: CronJob) -> int:
        value = job.payload.summary_window
        if isinstance(value, int) and value > 0:
            return value
        return self.summary_window

    def _build_tools(self, job: CronJob) -> "ToolRegistry":
        tools = create_tools(
            workspace=self.workspace,
            exec_config=self.exec_config,
            restrict_to_workspace=self.restrict_to_workspace,
            web_search_api_key=self.web_search_api_key,
            web_search_config=self._web_search_config,
            web_fetch_config=self._web_fetch_config,
        )

        # TODO: enforce per-job tool whitelist from `job.payload.tools`.
        if job.payload.tools:
            logger.debug(
                "Cron job {} has tools whitelist configured (not yet enforced): {}",
                job.id,
                job.payload.tools,
            )

        return tools

    def _build_system_prompt(
        self,
        *,
        job: CronJob,
        context_content: str,
        summaries: list[LogEntry],
    ) -> str:
        history = "\n\n".join(
            f"[{entry.timestamp}]\n{entry.content}" for entry in summaries if entry.content
        )
        if not history:
            history = "(No previous summaries.)"

        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        return "\n\n".join(
            [
                "# Cron Agent",
                "You are executing a scheduled task. Follow the instructions in your context "
                "precisely.\nOnly report when there is something actionable. High signal-to-noise.",
                "## Rules\n"
                "- Complete only the assigned task.\n"
                "- Be thorough in execution, concise in your final report.\n"
                "- Do not reference previous conversations - your history is in the summaries below.",
                context_content,
                "## Recent Execution History\n" + history,
                f"## Current Run\nTime: {now}\nJob: {job.name} ({job.id})",
            ]
        )


class _CronLoopHooks:
    """Loop hooks for isolated cron-agent execution."""

    def __init__(self, *, log: CronLog, provider: LLMProvider, model: str, job_id: str):
        self._log = log
        self._provider = provider
        self._model = model
        self._job_id = job_id

    def before_llm_call(self, messages: list[dict[str, Any]], meta: LoopMetadata) -> None:
        return None

    def on_tool_result(
        self,
        tool_name: str,
        tool_id: str,
        arguments: dict[str, Any],
        result: str,
        messages: list[dict[str, Any]],
        meta: LoopMetadata,
    ) -> None:
        self._log.append(
            _make_entry(
                chat_id=self._job_id,
                role="tool",
                content=(
                    f"Calling {tool_name} with arguments: "
                    f"{json.dumps(arguments, ensure_ascii=False)}"
                ),
                tool_name=tool_name,
                tool_result=result,
                origin="cron",
            )
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
        return None

    async def on_loop_exhausted(
        self,
        messages: list[dict[str, Any]],
        meta: LoopMetadata,
    ) -> str | None:
        messages.append(
            {
                "role": "user",
                "content": (
                    "You have reached the maximum number of tool iterations. "
                    "Do NOT call any more tools. Provide a concise final report with: "
                    "Outcome, Key findings, Open issues, and Failed actions (if any)."
                ),
            }
        )
        response = await self._provider.chat(messages=messages, tools=[], model=self._model)
        return response.content


def _make_entry(
    *,
    chat_id: str,
    role: str,
    content: str,
    tool_name: str | None = None,
    tool_result: str | None = None,
    entry_type: str = "message",
    origin: str = "user",
) -> LogEntry:
    return LogEntry(
        timestamp=datetime.now().isoformat(),
        channel="cron",
        chat_id=chat_id,
        role=role,
        content=content,
        tool_name=tool_name,
        tool_result=tool_result,
        entry_type=entry_type,
        origin=origin,
    )
