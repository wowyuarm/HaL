from __future__ import annotations

from pathlib import Path

from hal.capabilities.tools.spawn import SpawnTool
from hal.core.ports import SubagentExecutionResult


def test_format_result_includes_structured_subagent_metadata() -> None:
    details = SubagentExecutionResult(
        content="done",
        artifact_path=Path("/tmp/report.md"),
        total_tokens=42,
        record_id="abc123",
        status="partial",
        has_side_effects=True,
        tools_used=["fs", "web_search"],
        tool_call_counts={"fs": 2, "web_search": 1},
        files_modified=["/tmp/report.md"],
        commands_run=["ls -la"],
        tool_errors=["web_search: Error: Invalid parameters"],
        missing_artifacts=[Path("/tmp/missing.md")],
        log_path=Path("/tmp/subagent-log.jsonl"),
    )

    text = SpawnTool._format_result(details)

    assert "[Subagent Record ID] abc123" in text
    assert "[Subagent Status] partial" in text
    assert "[Subagent Artifact] /tmp/report.md" in text
    assert "[Subagent Log] /tmp/subagent-log.jsonl" in text
    assert "[Subagent Total Tokens] 42" in text
    assert "[Subagent Tools Used] [\"fs\", \"web_search\"]" in text
    assert "[Subagent Tool Counts] {\"fs\": 2, \"web_search\": 1}" in text
    assert "[Subagent Has Side Effects] true" in text
    assert "[Subagent Files Modified] [\"/tmp/report.md\"]" in text
    assert "[Subagent Commands Run] [\"ls -la\"]" in text
    assert "[Subagent Tool Errors] [\"web_search: Error: Invalid parameters\"]" in text
    assert "[Subagent Missing Artifacts] [\"/tmp/missing.md\"]" in text
