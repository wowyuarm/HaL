from __future__ import annotations

from pathlib import Path

from hal.workspace.system_files import SystemRepository


def test_load_bootstrap_documents(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    system = workspace / "system"
    system.mkdir(parents=True)
    (system / "SOUL.md").write_text("soul", encoding="utf-8")
    (system / "INSTRUCTIONS.md").write_text("instructions", encoding="utf-8")

    repo = SystemRepository(workspace)

    documents = repo.load_bootstrap_documents(files=["SOUL.md", "INSTRUCTIONS.md"])

    assert [document.name for document in documents] == ["SOUL.md", "INSTRUCTIONS.md"]
    assert [document.content for document in documents] == ["soul", "instructions"]


def test_load_bootstrap_documents_skips_missing_files(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    system = workspace / "system"
    system.mkdir(parents=True)
    (system / "SOUL.md").write_text("soul", encoding="utf-8")

    repo = SystemRepository(workspace)

    documents = repo.load_bootstrap_documents(files=["SOUL.md", "INSTRUCTIONS.md"])

    assert [document.name for document in documents] == ["SOUL.md"]
