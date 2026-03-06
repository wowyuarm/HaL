"""Result parsing, status classification, and execution logging for subagents."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from hal.core.runtime.loop import LoopMetadata
from hal.workspace import ArtifactRepository, SubagentExecutionRecord

_ARTIFACT_PATH_RE = re.compile(r"(/[^`'\"<>\s)]+\.md)\b")
_PARTIAL_INDICATOR_RE = re.compile(
    r"\b(could not|couldn't|unable|not able|hard blocker|incomplete|remaining|blocked)\b",
    re.IGNORECASE,
)


def append_execution_log(
    *,
    workspace: Path,
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
        repository = ArtifactRepository(workspace)
        display_label = label or task[:40] + ("..." if len(task) > 40 else "")
        record = SubagentExecutionRecord(
            id=task_id,
            timestamp=datetime.now().isoformat(timespec="seconds"),
            label=display_label,
            task=task,
            iterations=meta.iterations,
            tools_used=meta.tools_used,
            tool_call_counts=meta.tool_call_counts,
            has_side_effects=meta.has_side_effects,
            files_modified=meta.files_modified,
            commands_run=meta.commands_run,
            tool_errors=tool_errors,
            tokens=meta.total_usage.get("total_tokens", 0),
            result=result,
            artifacts=[str(path) for path in artifacts],
            missing_artifacts=[str(path) for path in missing_artifacts],
            status=status,
        )
        return repository.append_subagent_execution(record)
    except Exception as e:
        logger.warning(f"Failed to append subagent execution log: {e}")
        return None


def extract_artifact_paths(result: str) -> tuple[list[Path], list[Path]]:
    """Extract and validate absolute markdown artifact paths referenced in output."""
    candidates = [
        Path(raw_path)
        for raw_path in dict.fromkeys(_ARTIFACT_PATH_RE.findall(result))
        if Path(raw_path).is_absolute()
    ]
    return ArtifactRepository.partition_existing_markdown_paths(candidates)


def extract_tool_errors(loop_messages: list[dict[str, Any]]) -> list[str]:
    """Collect unique tool errors from loop messages for observability."""
    raw_errors = [
        _format_tool_error(msg)
        for msg in loop_messages
        if isinstance(msg, dict) and msg.get("role") == "tool"
    ]
    return [item for item in dict.fromkeys(raw_errors) if item]


def _format_tool_error(msg: dict[str, Any]) -> str | None:
    """Return a normalized error summary for one tool message."""
    content = str(msg.get("content", "")).strip()
    if not content.startswith("Error"):
        return None
    name = str(msg.get("name") or "tool")
    summary = content.splitlines()[0][:240]
    return f"{name}: {summary}"


def classify_status(
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
