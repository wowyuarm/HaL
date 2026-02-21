from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from hal.capabilities.skills.loader import SkillsLoader


def _write_skill(skills_dir: Path, name: str, frontmatter: str, body: str = "# Body\n") -> Path:
    skill_dir = skills_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(frontmatter + "\n" + body, encoding="utf-8")
    return skill_file


def _make_loader(tmp_path: Path) -> tuple[SkillsLoader, Path]:
    ws = tmp_path / "ws"
    skills = ws / "skills"
    skills.mkdir(parents=True)
    return SkillsLoader(workspace=ws), skills


def test_list_skills_basic(tmp_path: Path) -> None:
    loader, skills = _make_loader(tmp_path)

    _write_skill(skills, "weather", """---
name: weather
description: Weather skill
---""")
    _write_skill(skills, "github", """---
name: github
description: GitHub skill
---""")

    result = loader.list_skills(filter_unavailable=False)
    names = [s["name"] for s in result]
    assert "weather" in names
    assert "github" in names


def test_list_skills_filters_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    loader, skills = _make_loader(tmp_path)

    _write_skill(skills, "needcurl", """---
name: needcurl
description: Needs curl
requires_bins: ["curl"]
---""")

    monkeypatch.setattr(shutil, "which", lambda _: None)
    assert loader.list_skills(filter_unavailable=True) == []

    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/curl")
    result = loader.list_skills(filter_unavailable=True)
    assert [s["name"] for s in result] == ["needcurl"]


def test_build_skills_summary_escapes_xml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    loader, skills = _make_loader(tmp_path)

    _write_skill(skills, "xml&skill", """---
name: xml&skill
description: Use <x> & y
requires_bins: ["curl"]
---""")

    monkeypatch.setattr(shutil, "which", lambda _: None)
    summary = loader.build_skills_summary()

    assert "<skills>" in summary
    assert 'available="false"' in summary
    assert "xml&amp;skill" in summary
    assert "Use &lt;x&gt; &amp; y" in summary


def test_load_skills_for_context_strips_frontmatter(tmp_path: Path) -> None:
    loader, skills = _make_loader(tmp_path)

    _write_skill(skills, "demo", """---
name: demo
description: demo
---""", "# Demo\n\nHello\n")

    content = loader.load_skills_for_context(["demo", "missing"])
    assert "### Skill: demo" in content
    assert "---" not in content
    assert "Hello" in content


def test_get_always_skills_respects_requirements(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    loader, skills = _make_loader(tmp_path)

    _write_skill(skills, "always_env", """---
name: always_env
description: needs env
always: true
requires_env: ["FOO"]
---""")

    monkeypatch.delenv("FOO", raising=False)
    assert loader.get_always_skills() == []

    monkeypatch.setenv("FOO", "1")
    assert loader.get_always_skills() == ["always_env"]


def test_get_skill_metadata_missing_returns_none(tmp_path: Path) -> None:
    loader, _ = _make_loader(tmp_path)
    assert loader.get_skill_metadata("nope") is None


def test_parse_list_handles_edge_cases() -> None:
    assert SkillsLoader._parse_list("") == []
    assert SkillsLoader._parse_list("[]") == []
    assert SkillsLoader._parse_list('["gh"]') == ["gh"]
    assert SkillsLoader._parse_list('["a", "b"]') == ["a", "b"]
    assert SkillsLoader._parse_list("not-a-list") == ["not-a-list"]
