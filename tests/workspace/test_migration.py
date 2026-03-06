from __future__ import annotations

import json
from pathlib import Path

import hal.workspace.migration as migration_module
from hal.workspace import (
    export_workspace_migration_report,
    export_workspace_migration_rollback_script,
    migrate_workspace_v3,
    plan_workspace_v3_migration,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_plan_workspace_v3_migration_lists_expected_moves(tmp_path: Path) -> None:
    _write(tmp_path / "SOUL.md", "identity")
    _write(tmp_path / "MEMORY.md", "memory")
    _write(tmp_path / "threads" / "a" / "STATE.md", "# A")
    _write(tmp_path / "logs" / "events.jsonl", "{}")
    _write(tmp_path / "memory" / "vectors" / "index.bin", "x")

    actions = plan_workspace_v3_migration(tmp_path)

    move_targets = {action.destination for action in actions if action.kind == "move"}
    assert tmp_path / "system" / "SOUL.md" in move_targets
    assert tmp_path / "system" / "MEMORY.md" in move_targets
    assert tmp_path / "work" / "threads" in move_targets
    assert tmp_path / "runtime" / "logs" in move_targets
    assert tmp_path / "data" / "vectors" in move_targets


def test_migrate_workspace_v3_dry_run_is_non_destructive(tmp_path: Path) -> None:
    _write(tmp_path / "skills" / "notes" / "SKILL.md", "# Skill")
    _write(tmp_path / "auth.yaml", "providers: {}")

    report = migrate_workspace_v3(tmp_path, dry_run=True)

    assert report.applied is False
    assert (tmp_path / "skills" / "notes" / "SKILL.md").exists()
    assert (tmp_path / "auth.yaml").exists()
    assert not (tmp_path / "capabilities" / "skills").exists()
    assert not (tmp_path / "system" / "auth.yaml").exists()


def test_migrate_workspace_v3_applies_moves_and_is_idempotent(tmp_path: Path) -> None:
    _write(tmp_path / "INSTRUCTIONS.md", "# Instructions")
    _write(tmp_path / "threads" / "x" / "STATE.md", "# X")
    _write(tmp_path / "artifacts" / "subagent" / "r.md", "# report")

    first = migrate_workspace_v3(tmp_path)
    second = migrate_workspace_v3(tmp_path)

    assert first.applied is True
    assert second.applied is True
    assert (tmp_path / "system" / "INSTRUCTIONS.md").exists()
    assert (tmp_path / "work" / "threads" / "x" / "STATE.md").exists()
    assert (tmp_path / "data" / "artifacts" / "subagent" / "r.md").exists()
    assert not (tmp_path / "threads").exists()
    assert not (tmp_path / "artifacts").exists()
    assert first.rollback_hints
    assert first.rollback_hints[0].startswith("mv ")


def test_migrate_workspace_v3_rolls_back_when_apply_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write(tmp_path / "INSTRUCTIONS.md", "# Instructions")
    _write(tmp_path / "threads" / "x" / "STATE.md", "# X")

    original_apply_move = migration_module._apply_move
    call_count = 0

    def _failing_apply_move(action):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("boom")
        original_apply_move(action)

    monkeypatch.setattr(migration_module, "_apply_move", _failing_apply_move)

    report = migrate_workspace_v3(tmp_path, dry_run=False, rollback_on_error=True)

    assert report.applied is False
    assert report.rolled_back is True
    assert any("Migration failed:" in warning for warning in report.warnings)
    assert any("Rollback completed" in warning for warning in report.warnings)
    assert (tmp_path / "INSTRUCTIONS.md").exists()
    assert (tmp_path / "threads" / "x" / "STATE.md").exists()
    assert not (tmp_path / "system" / "INSTRUCTIONS.md").exists()
    assert not (tmp_path / "work" / "threads" / "x" / "STATE.md").exists()


def test_migrate_workspace_v3_reports_conflicts(tmp_path: Path) -> None:
    _write(tmp_path / "SOUL.md", "root soul")
    _write(tmp_path / "system" / "SOUL.md", "new soul")

    report = migrate_workspace_v3(tmp_path)

    assert report.applied is True
    assert report.warnings
    assert "Skipped move due to existing destination" in report.warnings[0]
    assert (tmp_path / "SOUL.md").exists()
    assert (tmp_path / "system" / "SOUL.md").exists()


def test_export_workspace_migration_report_writes_json(tmp_path: Path) -> None:
    _write(tmp_path / "threads" / "x" / "STATE.md", "# X")

    report = migrate_workspace_v3(tmp_path, dry_run=True)
    output_path = tmp_path / "reports" / "workspace-migration.json"
    written_path = export_workspace_migration_report(report, destination=output_path)

    assert written_path == output_path
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["root"] == str(tmp_path)
    assert payload["applied"] is False
    assert payload["rolled_back"] is False
    assert isinstance(payload["actions"], list)
    assert isinstance(payload["rollback_hints"], list)


def test_export_workspace_migration_rollback_script_writes_executable(tmp_path: Path) -> None:
    _write(tmp_path / "threads" / "x" / "STATE.md", "# X")

    report = migrate_workspace_v3(tmp_path, dry_run=True)
    script_path = tmp_path / "reports" / "rollback.sh"
    written_path = export_workspace_migration_rollback_script(report, destination=script_path)

    assert written_path == script_path
    script_text = script_path.read_text(encoding="utf-8")
    assert script_text.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in script_text
    if report.rollback_hints:
        assert "mv " in script_text
