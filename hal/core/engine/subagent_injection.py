"""Helpers for parsing and rendering subagent result injections."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from hal.core.context.token_budget import trim_text_to_token_budget

_SUBAGENT_TOKEN_RE = re.compile(r"\[Subagent Total Tokens\]\s*(\d+)")
_SUBAGENT_ARTIFACT_RE = re.compile(r"^\[Subagent Artifact\]\s*(.+)$", re.MULTILINE)
_SUBAGENT_RECORD_RE = re.compile(r"^\[Subagent Record ID\]\s*(.+)$", re.MULTILINE)
_SUBAGENT_STATUS_RE = re.compile(r"^\[Subagent Status\]\s*(.+)$", re.MULTILINE)
_SUBAGENT_TOOLS_USED_RE = re.compile(r"^\[Subagent Tools Used\]\s*(.+)$", re.MULTILINE)
_SUBAGENT_TOOL_COUNTS_RE = re.compile(r"^\[Subagent Tool Counts\]\s*(.+)$", re.MULTILINE)
_SUBAGENT_HAS_SIDE_EFFECTS_RE = re.compile(r"^\[Subagent Has Side Effects\]\s*(.+)$", re.MULTILINE)
_SUBAGENT_FILES_MODIFIED_RE = re.compile(r"^\[Subagent Files Modified\]\s*(.+)$", re.MULTILINE)
_SUBAGENT_COMMANDS_RUN_RE = re.compile(r"^\[Subagent Commands Run\]\s*(.+)$", re.MULTILINE)
_SUBAGENT_TOOL_ERRORS_RE = re.compile(r"^\[Subagent Tool Errors\]\s*(.+)$", re.MULTILINE)
_SUBAGENT_MISSING_ARTIFACTS_RE = re.compile(
    r"^\[Subagent Missing Artifacts\]\s*(.+)$", re.MULTILINE
)

_SUBAGENT_HISTORY_MAX_TOKENS = 200
# 0 = no truncation for same-turn runtime injection to main agent.
_SUBAGENT_RUNTIME_MAX_TOKENS = 0


@dataclass
class ParsedSubagentResult:
    content: str
    artifact_path: str | None
    total_tokens: int
    record_id: str | None
    status: str
    tools_used: list[str]
    tool_call_counts: dict[str, int]
    has_side_effects: bool
    files_modified: list[str]
    commands_run: list[str]
    tool_errors: list[str]
    missing_artifacts: list[str]


def _extract_spawn_total_tokens(messages: list[dict[str, Any]]) -> int:
    """Sum known spawn token usage tags from tool message content."""
    total = 0
    for msg in messages:
        content = str(msg.get("content", ""))
        for match in _SUBAGENT_TOKEN_RE.findall(content):
            total += int(match)
    return total


def _split_subagent_tool_result(result: str) -> ParsedSubagentResult:
    """Split sync spawn tool result into content + structured metadata."""
    artifact_match = _SUBAGENT_ARTIFACT_RE.search(result)
    artifact_path = artifact_match.group(1).strip() if artifact_match else None
    record_match = _SUBAGENT_RECORD_RE.search(result)
    record_id = record_match.group(1).strip() if record_match else None
    status_match = _SUBAGENT_STATUS_RE.search(result)
    status = status_match.group(1).strip().lower() if status_match else ""

    total_tokens = 0
    for token in _SUBAGENT_TOKEN_RE.findall(result):
        total_tokens += int(token)

    tools_used = _parse_json_list_marker(_SUBAGENT_TOOLS_USED_RE.search(result))
    tool_call_counts = _parse_json_dict_marker(_SUBAGENT_TOOL_COUNTS_RE.search(result))
    has_side_effects = _parse_bool_marker(_SUBAGENT_HAS_SIDE_EFFECTS_RE.search(result))
    files_modified = _parse_json_list_marker(_SUBAGENT_FILES_MODIFIED_RE.search(result))
    commands_run = _parse_json_list_marker(_SUBAGENT_COMMANDS_RUN_RE.search(result))
    tool_errors = _parse_json_list_marker(_SUBAGENT_TOOL_ERRORS_RE.search(result))
    missing_artifacts = _parse_json_list_marker(_SUBAGENT_MISSING_ARTIFACTS_RE.search(result))

    cleaned_lines: list[str] = []
    marker_prefixes = (
        "[Subagent Artifact]",
        "[Subagent Record ID]",
        "[Subagent Log]",
        "[Subagent Total Tokens]",
        "[Subagent Status]",
        "[Subagent Tools Used]",
        "[Subagent Tool Counts]",
        "[Subagent Has Side Effects]",
        "[Subagent Files Modified]",
        "[Subagent Commands Run]",
        "[Subagent Tool Errors]",
        "[Subagent Missing Artifacts]",
    )
    for line in result.splitlines():
        if line.startswith(marker_prefixes):
            continue
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines).strip() or result.strip()

    if not status:
        status = "failed" if cleaned.startswith("Error:") else "completed"

    return ParsedSubagentResult(
        content=cleaned,
        artifact_path=artifact_path,
        total_tokens=total_tokens,
        record_id=record_id,
        status=status,
        tools_used=tools_used,
        tool_call_counts=tool_call_counts,
        has_side_effects=has_side_effects,
        files_modified=files_modified,
        commands_run=commands_run,
        tool_errors=tool_errors,
        missing_artifacts=missing_artifacts,
    )


def _parse_json_list_marker(match: re.Match[str] | None) -> list[str]:
    """Parse a marker payload as a list with graceful fallbacks."""
    if not match:
        return []
    raw = match.group(1).strip()
    if not raw:
        return []
    try:
        value = json.loads(raw)
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
    except Exception:
        pass
    return [part.strip() for part in raw.split(",") if part.strip()]


def _parse_json_dict_marker(match: re.Match[str] | None) -> dict[str, int]:
    """Parse a marker payload as a dict[str, int]."""
    if not match:
        return {}
    raw = match.group(1).strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(value, dict):
        return {}

    parsed: dict[str, int] = {}
    for k, v in value.items():
        if isinstance(v, int):
            parsed[str(k)] = v
        elif isinstance(v, float):
            parsed[str(k)] = int(v)
    return parsed


def _parse_bool_marker(match: re.Match[str] | None) -> bool:
    """Parse a marker payload as a boolean value."""
    if not match:
        return False
    return match.group(1).strip().lower() in {"1", "true", "yes", "y"}


def _build_subagent_injection(
    *,
    label: str,
    content: str,
    status: str,
    background: bool,
    record_id: str | None,
    artifact_path: str | None,
    total_tokens: int,
    tools_used: list[str] | None = None,
    tool_call_counts: dict[str, int] | None = None,
    has_side_effects: bool = False,
    files_modified: list[str] | None = None,
    commands_run: list[str] | None = None,
    tool_errors: list[str] | None = None,
    missing_artifacts: list[str] | None = None,
    max_tokens: int = _SUBAGENT_HISTORY_MAX_TOKENS,
) -> str:
    """Build compact subagent injection content for next-loop context."""
    is_error = status in {"failed", "error"} or content.startswith("Error:")
    body = content
    truncated = False
    if not is_error and max_tokens > 0:
        trimmed = trim_text_to_token_budget(body, max_tokens, suffix=" [...]")
        truncated = trimmed != body
        body = trimmed

    if background:
        text = f"[Background subagent '{label}' {status}]\n\nResult:\n{body}"
    else:
        text = f"[Subagent Result: {label}]\n\n{body}"

    if truncated:
        text += "\n\n[Full result saved to subagent artifact file]"
    if record_id:
        text += f"\n[Subagent Record ID] {record_id}"
    if artifact_path:
        text += f"\n[Subagent Artifact] {artifact_path}"
    if total_tokens:
        text += f"\n[Subagent Total Tokens] {total_tokens}"
    text += f"\n[Subagent Status] {status}"

    if tools_used:
        text += f"\n[Subagent Tools Used] {json.dumps(tools_used, ensure_ascii=False)}"
    if tool_call_counts:
        text += f"\n[Subagent Tool Counts] {json.dumps(tool_call_counts, ensure_ascii=False)}"
    text += f"\n[Subagent Has Side Effects] {'true' if has_side_effects else 'false'}"
    if files_modified:
        text += f"\n[Subagent Files Modified] {json.dumps(files_modified, ensure_ascii=False)}"
    if commands_run:
        text += f"\n[Subagent Commands Run] {json.dumps(commands_run, ensure_ascii=False)}"
    if tool_errors:
        text += f"\n[Subagent Tool Errors] {json.dumps(tool_errors, ensure_ascii=False)}"
    if missing_artifacts:
        text += (
            f"\n[Subagent Missing Artifacts] {json.dumps(missing_artifacts, ensure_ascii=False)}"
        )
    return text
