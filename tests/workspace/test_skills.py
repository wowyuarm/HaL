from __future__ import annotations

from pathlib import Path

from hal.workspace.skills import SKILL_FILENAME, SkillRepository


def test_skill_repository_uses_legacy_skills_dir_by_default(tmp_path: Path) -> None:
    repository = SkillRepository(tmp_path)

    assert repository.skills_dir() == tmp_path / "skills"
    assert repository.skill_markdown_path("notes") == tmp_path / "skills" / "notes" / SKILL_FILENAME


def test_skill_repository_prefers_v3_capabilities_skills_dir(tmp_path: Path) -> None:
    (tmp_path / "capabilities" / "skills").mkdir(parents=True)
    repository = SkillRepository(tmp_path)

    assert repository.skills_dir() == tmp_path / "capabilities" / "skills"
    assert repository.skill_markdown_path("notes") == (
        tmp_path / "capabilities" / "skills" / "notes" / SKILL_FILENAME
    )
