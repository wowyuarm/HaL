from __future__ import annotations

from pathlib import Path

import pytest

from hal.capabilities.skills.loader import SkillsLoader
from hal.core.context.units import (
    build_skill_unit_manifests,
    build_skill_units,
    build_thread_unit_manifests,
    build_thread_units,
    render_skill_unit_registry_xml,
    render_thread_unit_registry_markdown,
)
from hal.workspace import ThreadRepository


def _write_skill(skills_dir: Path, name: str, frontmatter: str, body: str = "# Body\n") -> Path:
    skill_dir = skills_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(frontmatter + "\n" + body, encoding="utf-8")
    return skill_file


def test_build_skill_unit_manifests_captures_availability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "ws"
    skills_dir = workspace / "skills"
    skills_dir.mkdir(parents=True)
    _write_skill(
        skills_dir,
        "needcurl",
        """---
name: needcurl
description: Needs curl
requires_bins: ["curl"]
---""",
    )
    _write_skill(
        skills_dir,
        "notes",
        """---
name: notes
description: Plain note helper
---""",
    )
    loader = SkillsLoader(workspace)

    monkeypatch.setattr("shutil.which", lambda binary: "/usr/bin/curl" if binary == "curl" else None)
    manifests = build_skill_unit_manifests(loader)

    assert [manifest.key for manifest in manifests] == ["needcurl", "notes"]
    assert manifests[0].kind == "skill"
    assert manifests[0].available is True
    assert manifests[0].location.endswith("skills/needcurl/SKILL.md")


def test_build_skill_units_returns_context_unit_objects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "ws"
    skills_dir = workspace / "skills"
    skills_dir.mkdir(parents=True)
    _write_skill(
        skills_dir,
        "notes",
        """---
name: notes
description: Plain note helper
---""",
    )
    loader = SkillsLoader(workspace)
    monkeypatch.setattr("shutil.which", lambda _: None)

    units = build_skill_units(loader)

    assert len(units) == 1
    assert units[0].key == "notes"
    assert units[0].available is True
    assert units[0].manifest().kind == "skill"
    assert units[0].load() is not None
    assert units[0].priority() == 100
    assert units[0].related() == ()


def test_build_thread_unit_manifests_reflects_workspace_state(tmp_path: Path) -> None:
    thread_dir = tmp_path / "threads" / "hal-architecture"
    thread_dir.mkdir(parents=True)
    (thread_dir / "STATE.md").write_text(
        "# HaL Architecture\nStatus: active\n\n## Goal\nRefine the context system.\n",
        encoding="utf-8",
    )

    manifests = build_thread_unit_manifests(ThreadRepository(tmp_path), max_entries=20)

    assert len(manifests) == 1
    assert manifests[0].kind == "thread"
    assert manifests[0].key == "hal-architecture"
    assert manifests[0].status == "active"
    assert manifests[0].description == "Refine the context system."
    assert manifests[0].location == "threads/hal-architecture/STATE.md"


def test_build_thread_units_returns_context_unit_objects(tmp_path: Path) -> None:
    thread_dir = tmp_path / "threads" / "github-actions"
    thread_dir.mkdir(parents=True)
    (thread_dir / "STATE.md").write_text(
        "# GitHub Actions\nStatus: active\n\n## Goal\nShip automation.\n",
        encoding="utf-8",
    )

    units = build_thread_units(ThreadRepository(tmp_path), max_entries=20)

    assert len(units) == 1
    assert units[0].key == "github-actions"
    assert units[0].status == "active"
    assert units[0].manifest().kind == "thread"
    assert "Ship automation." in (units[0].load() or "")
    assert units[0].priority() == 200
    assert units[0].related() == ()
    assert units[0].to_thread_snapshot()["slug"] == "github-actions"
    assert units[0].to_thread_entry_snapshot()["status"] == "active"


def test_render_skill_unit_registry_xml_escapes_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "ws"
    skills_dir = workspace / "skills"
    skills_dir.mkdir(parents=True)
    _write_skill(
        skills_dir,
        "xml&skill",
        """---
name: xml&skill
description: Use <x> & y
---""",
    )
    loader = SkillsLoader(workspace)
    monkeypatch.setattr("shutil.which", lambda _: None)

    text = render_skill_unit_registry_xml(build_skill_unit_manifests(loader))

    assert "<skills>" in text
    assert "xml&amp;skill" in text
    assert "Use &lt;x&gt; &amp; y" in text


def test_render_thread_unit_registry_markdown_includes_status(tmp_path: Path) -> None:
    thread_dir = tmp_path / "threads" / "github-actions"
    thread_dir.mkdir(parents=True)
    (thread_dir / "STATE.md").write_text(
        "# GitHub Actions\nStatus: active\n\n## Goal\nShip automation.\n",
        encoding="utf-8",
    )

    text = render_thread_unit_registry_markdown(
        build_thread_unit_manifests(ThreadRepository(tmp_path), max_entries=20)
    )

    assert "# Threads" in text
    assert "GitHub Actions [active]" in text
    assert "threads/github-actions/STATE.md" in text
