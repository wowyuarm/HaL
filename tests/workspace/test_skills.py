from __future__ import annotations

from pathlib import Path

from hal.workspace.skills import SKILL_FILENAME, SkillRepository


def test_skill_repository_resolves_v3_paths(tmp_path: Path) -> None:
    repository = SkillRepository(tmp_path)

    assert repository.skills_dir() == tmp_path / "capabilities" / "skills"
    assert repository.skill_markdown_path("notes") == (
        tmp_path / "capabilities" / "skills" / "notes" / SKILL_FILENAME
    )
