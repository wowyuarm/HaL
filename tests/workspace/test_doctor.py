from __future__ import annotations

from pathlib import Path

from hal.workspace import WorkspaceDoctor


def test_workspace_doctor_reports_legacy_paths_and_unmanaged_dirs(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "skills" / "telegraph").mkdir(parents=True)
    (workspace / "config.yaml").write_text(
        "agents:\n  defaults:\n    model: test\n", encoding="utf-8"
    )
    (workspace / "media" / "received").mkdir(parents=True)
    (workspace / "media").mkdir(exist_ok=True)
    (workspace / "data" / "vectors").mkdir(parents=True)
    (workspace / ".mypy_cache").mkdir(parents=True)
    runtime_sessions = workspace / "runtime" / "sessions"
    runtime_sessions.mkdir(parents=True)
    (runtime_sessions / "active_sessions.json").write_text("{}", encoding="utf-8")

    report = WorkspaceDoctor(workspace).analyze()

    operation_targets = {
        operation.target.relative_to(workspace).as_posix() for operation in report.operations
    }
    issue_summaries = {issue.summary for issue in report.issues}

    assert "system/config.yaml" in operation_targets
    assert "capabilities/skills" in operation_targets
    assert "data/media/received" in operation_targets
    assert "data/vectors" in operation_targets
    assert "runtime/sessions" in operation_targets
    assert any(".mypy_cache" in summary for summary in issue_summaries)


def test_workspace_doctor_apply_moves_safe_legacy_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "skills" / "blog").mkdir(parents=True)
    (workspace / "skills" / "blog" / "SKILL.md").write_text("blog skill", encoding="utf-8")
    (workspace / "config.yaml").write_text(
        "agents:\n  defaults:\n    model: test\n", encoding="utf-8"
    )
    (workspace / "media" / "received").mkdir(parents=True)
    (workspace / "media" / "received" / "note.txt").write_text("hello", encoding="utf-8")
    (workspace / "data" / "vectors").mkdir(parents=True)
    runtime_sessions = workspace / "runtime" / "sessions"
    runtime_sessions.mkdir(parents=True)
    (runtime_sessions / "active_sessions.json").write_text("{}", encoding="utf-8")

    doctor = WorkspaceDoctor(workspace)
    report = doctor.analyze()
    results = doctor.apply(report)

    assert {result.status for result in results} == {"applied"}
    assert not (workspace / "skills").exists()
    assert not (workspace / "config.yaml").exists()
    assert not (workspace / "media" / "received").exists()
    assert not (workspace / "data" / "vectors").exists()
    assert not runtime_sessions.exists()
    assert (workspace / "capabilities" / "skills" / "blog" / "SKILL.md").read_text(
        encoding="utf-8"
    ) == "blog skill"
    assert (workspace / "system" / "config.yaml").exists()
    assert (workspace / "data" / "media" / "received" / "note.txt").read_text(
        encoding="utf-8"
    ) == "hello"


def test_workspace_doctor_skips_move_when_canonical_target_already_exists(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "skills" / "legacy").mkdir(parents=True)
    (workspace / "capabilities" / "skills" / "current").mkdir(parents=True)

    report = WorkspaceDoctor(workspace).analyze()

    assert report.operations == ()
    assert any("manual merge" in issue.detail for issue in report.issues)


def test_workspace_doctor_keeps_nonempty_legacy_media_dir_for_manual_review(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "media" / "note.txt").parent.mkdir(parents=True)
    (workspace / "media" / "note.txt").write_text("legacy", encoding="utf-8")

    report = WorkspaceDoctor(workspace).analyze()

    assert report.operations == ()
    assert all("Empty legacy directory can be removed: media" != issue.summary for issue in report.issues)
