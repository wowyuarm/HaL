from __future__ import annotations

import json
from pathlib import Path

from hal.workspace import ArtifactRepository, SubagentExecutionRecord


def test_append_subagent_execution_writes_jsonl(tmp_path: Path) -> None:
    repo = ArtifactRepository(tmp_path)
    record = SubagentExecutionRecord(
        id="task-1",
        timestamp="2026-03-06T20:00:00",
        label="research",
        task="do work",
        iterations=2,
        tools_used=["fs"],
        tool_call_counts={"fs": 1},
        has_side_effects=False,
        files_modified=[],
        commands_run=[],
        tool_errors=[],
        tokens=123,
        result="done",
        artifacts=[],
        missing_artifacts=[],
        status="completed",
    )

    log_path = repo.append_subagent_execution(record)

    assert log_path == tmp_path / "artifacts" / "subagent" / "subagent-log.jsonl"
    payload = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert payload["id"] == "task-1"
    assert payload["status"] == "completed"


def test_partition_existing_markdown_paths_splits_existing_and_missing(tmp_path: Path) -> None:
    existing = tmp_path / "report.md"
    existing.write_text("# Report\n", encoding="utf-8")
    missing = tmp_path / "missing.md"

    artifacts, absent = ArtifactRepository.partition_existing_markdown_paths([existing, missing])

    assert artifacts == [existing]
    assert absent == [missing]
