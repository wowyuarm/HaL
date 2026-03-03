"""Result parsing, status classification, and execution logging for subagents."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from hal.core.runtime.loop import LoopMetadata

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
        artifact_dir = workspace / "artifacts" / "subagent"
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


def extract_artifact_paths(result: str) -> tuple[list[Path], list[Path]]:
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


def extract_tool_errors(loop_messages: list[dict[str, Any]]) -> list[str]:
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
