from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from hal.capabilities.skills.loader import SkillsLoader


def _write_skill(dir_path: Path, name: str, frontmatter: str, body: str = "# Body\n") -> Path:
    skill_dir = dir_path / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(frontmatter + "\n" + body, encoding="utf-8")
    return skill_file


def test_list_skills_workspace_priority_and_dedup(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    builtin = tmp_path / "builtin"
    builtin.mkdir()

    # Same skill exists in both workspace + builtin → only workspace should be listed.
    _write_skill(
        builtin,
        "weather",
        """---
name: weather
description: builtin weather
metadata: {\"hal\":{\"requires\":{\"bins\":[\"curl\"]}}}
---""",
        "builtin body",
    )
    ws_skill_dir = ws / "skills"
    ws_skill_dir.mkdir()
    _write_skill(
        ws_skill_dir,
        "weather",
        """---
name: weather
description: workspace weather
metadata: {\"hal\":{\"requires\":{\"bins\":[]}}}
---""",
        "workspace body",
    )

    _write_skill(
        builtin,
        "github",
        """---
name: github
description: GitHub skill
metadata: {\"hal\":{\"requires\":{\"bins\":[\"gh\"]}}}
---""",
    )

    loader = SkillsLoader(workspace=ws, builtin_skills_dir=builtin)
    skills = loader.list_skills(filter_unavailable=False)

    names = [s["name"] for s in skills]
    assert "weather" in names
    assert "github" in names

    # Weather should come from workspace
    weather = next(s for s in skills if s["name"] == "weather")
    assert weather["source"] == "workspace"
    assert "ws/skills/weather/SKILL.md" in weather["path"].replace("\\", "/")


def test_list_skills_filters_unavailable_by_requirements(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    builtin = tmp_path / "builtin"
    builtin.mkdir()

    _write_skill(
        builtin,
        "needcurl",
        """---
name: needcurl
description: Needs curl
metadata: {\"hal\":{\"requires\":{\"bins\":[\"curl\"]}}}
---""",
    )

    loader = SkillsLoader(workspace=ws, builtin_skills_dir=builtin)

    monkeypatch.setattr(shutil, "which", lambda _: None)
    assert loader.list_skills(filter_unavailable=True) == []

    # If requirements pass, it should appear.
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/curl")
    skills = loader.list_skills(filter_unavailable=True)
    assert [s["name"] for s in skills] == ["needcurl"]


def test_build_skills_summary_includes_requires_and_escapes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    builtin = tmp_path / "builtin"
    builtin.mkdir()

    _write_skill(
        builtin,
        "xml&skill",
        """---
name: xml&skill
description: Use <x> & y
metadata: {\"hal\":{\"requires\":{\"bins\":[\"curl\"],\"env\":[\"FOO\"]}}}
---""",
    )

    loader = SkillsLoader(workspace=ws, builtin_skills_dir=builtin)

    monkeypatch.setattr(shutil, "which", lambda _: None)
    monkeypatch.delenv("FOO", raising=False)

    summary = loader.build_skills_summary()
    assert "<skills>" in summary
    assert "available=\"false\"" in summary

    # Escaping
    assert "xml&amp;skill" in summary
    assert "Use &lt;x&gt; &amp; y" in summary

    # Requirements detail
    assert "CLI: curl" in summary
    assert "ENV: FOO" in summary


def test_load_skills_for_context_strips_frontmatter(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    ws_skills = ws / "skills"
    ws_skills.mkdir()

    _write_skill(
        ws_skills,
        "demo",
        """---
name: demo
description: demo
metadata: {\"hal\":{}} 
---""",
        "# Demo\n\nHello\n",
    )

    loader = SkillsLoader(workspace=ws, builtin_skills_dir=None)
    content = loader.load_skills_for_context(["demo", "missing"])  # missing ignored

    assert "### Skill: demo" in content
    assert "---" not in content
    assert "Hello" in content


def test_get_always_skills_respects_requirements(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    builtin = tmp_path / "builtin"
    builtin.mkdir()

    _write_skill(
        builtin,
        "always_env",
        """---
name: always_env
description: needs env
metadata: {\"hal\":{\"always\":true,\"requires\":{\"env\":[\"FOO\"]}}}
---""",
    )

    loader = SkillsLoader(workspace=ws, builtin_skills_dir=builtin)

    monkeypatch.delenv("FOO", raising=False)
    assert loader.get_always_skills() == []

    monkeypatch.setenv("FOO", "1")
    assert loader.get_always_skills() == ["always_env"]


def test_invalid_metadata_json_is_ignored(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    builtin = tmp_path / "builtin"
    builtin.mkdir()

    _write_skill(
        builtin,
        "badmeta",
        """---
name: badmeta
description: bad metadata
metadata: not-json
---""",
    )

    loader = SkillsLoader(workspace=ws, builtin_skills_dir=builtin)
    # Should not crash; metadata treated as empty.
    meta = loader.get_skill_metadata("badmeta")
    assert meta is not None
    assert meta.get("metadata") == "not-json"

    # With no requirements, this should be considered available.
    skills = loader.list_skills(filter_unavailable=True)
    assert [s["name"] for s in skills] == ["badmeta"]


def test_get_skill_metadata_missing_returns_none(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    loader = SkillsLoader(workspace=ws, builtin_skills_dir=None)
    assert loader.get_skill_metadata("nope") is None
