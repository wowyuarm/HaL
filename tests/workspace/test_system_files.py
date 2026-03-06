from __future__ import annotations

from pathlib import Path

from hal.workspace.system_files import SystemRepository


def test_load_bootstrap_documents_prefers_primary_files(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "SOUL.md").write_text("soul", encoding="utf-8")
    (workspace / "INSTRUCTIONS.md").write_text("instructions", encoding="utf-8")
    (workspace / "USER.md").write_text("legacy user", encoding="utf-8")

    repo = SystemRepository(workspace)

    documents = repo.load_bootstrap_documents(
        primary_files=["SOUL.md", "INSTRUCTIONS.md"],
        legacy_files=["USER.md"],
    )

    assert [document.name for document in documents] == ["SOUL.md", "INSTRUCTIONS.md"]
    assert [document.content for document in documents] == ["soul", "instructions"]


def test_load_bootstrap_documents_falls_back_to_legacy_when_instructions_missing(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "SOUL.md").write_text("soul", encoding="utf-8")
    (workspace / "USER.md").write_text("legacy user", encoding="utf-8")
    (workspace / "AGENTS.md").write_text("legacy agents", encoding="utf-8")

    repo = SystemRepository(workspace)

    documents = repo.load_bootstrap_documents(
        primary_files=["SOUL.md", "INSTRUCTIONS.md"],
        legacy_files=["USER.md", "AGENTS.md"],
    )

    assert [document.name for document in documents] == ["SOUL.md", "USER.md", "AGENTS.md"]


def test_load_bootstrap_documents_skips_missing_files(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    repo = SystemRepository(workspace)

    documents = repo.load_bootstrap_documents(
        primary_files=["SOUL.md", "INSTRUCTIONS.md"],
        legacy_files=["USER.md"],
    )

    assert documents == []
