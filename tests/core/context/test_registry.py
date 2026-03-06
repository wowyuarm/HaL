from __future__ import annotations

from pathlib import Path

import pytest

from hal.capabilities.skills.loader import SkillsLoader
from hal.core.context.registry import ContextRegistry


def _write_skill(skills_dir: Path, name: str, frontmatter: str, body: str = "# Body\n") -> Path:
    skill_dir = skills_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(frontmatter + "\n" + body, encoding="utf-8")
    return skill_file


@pytest.fixture()
def registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ContextRegistry:
    workspace = tmp_path / "ws"
    skills_dir = workspace / "skills"
    thread_dir = workspace / "threads" / "hal-architecture"
    skills_dir.mkdir(parents=True)
    thread_dir.mkdir(parents=True)

    _write_skill(
        skills_dir,
        "notes",
        """---
name: notes
description: Plain note helper
---""",
    )
    (thread_dir / "STATE.md").write_text(
        "# HaL Architecture\nStatus: active\n\n## Goal\nRefine the context system.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/true")
    return ContextRegistry.from_workspace(
        workspace=workspace,
        skills_loader=SkillsLoader(workspace),
        max_thread_registry_size=20,
    )


def test_registry_builds_skill_and_thread_snapshots(registry: ContextRegistry) -> None:
    skill_snapshot = registry.skill_snapshot()
    thread_snapshot = registry.thread_snapshot()

    assert skill_snapshot[0]["name"] == "notes"
    assert skill_snapshot[0]["kind"] == "skill"
    assert len(thread_snapshot) == 1
    thread = thread_snapshot[0]
    assert thread["slug"] == "hal-architecture"
    assert thread["name"] == "HaL Architecture"
    assert thread["status"] == "active"
    assert thread["description"] == "Refine the context system."
    assert thread["state_path"] == "threads/hal-architecture/STATE.md"
    assert thread["priority"] == 200
    assert thread["pinned"] is False
    assert thread["related_threads"] == ()


def test_registry_renders_summaries_and_unified_snapshot(registry: ContextRegistry) -> None:
    unit_snapshot = registry.context_unit_snapshot()
    units = registry.context_units()
    skills_summary = registry.render_skill_summary()
    threads_summary = registry.render_thread_summary()

    assert {item["kind"] for item in unit_snapshot} == {"skill", "thread"}
    assert {unit.kind for unit in units} == {"skill", "thread"}
    assert "<skills>" in skills_summary
    assert "# Threads" in threads_summary


def test_registry_active_thread_entry_snapshot_filters_non_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "ws"
    skills_dir = workspace / "skills"
    active_dir = workspace / "threads" / "active-thread"
    paused_dir = workspace / "threads" / "paused-thread"
    skills_dir.mkdir(parents=True)
    active_dir.mkdir(parents=True)
    paused_dir.mkdir(parents=True)
    _write_skill(
        skills_dir,
        "notes",
        """---
name: notes
description: Plain note helper
---""",
    )
    (active_dir / "STATE.md").write_text(
        "# Active Thread\nStatus: active\n\n## Goal\nKeep moving.\n",
        encoding="utf-8",
    )
    (paused_dir / "STATE.md").write_text(
        "# Paused Thread\nStatus: paused\n\n## Goal\nWait for input.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/true")

    registry = ContextRegistry.from_workspace(
        workspace=workspace,
        skills_loader=SkillsLoader(workspace),
        max_thread_registry_size=20,
    )

    active_entries = registry.active_thread_entry_snapshot()

    assert [entry["slug"] for entry in active_entries] == ["active-thread"]


def test_registry_context_units_are_priority_ranked_and_related_keys_exposed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "ws"
    skills_dir = workspace / "skills"
    active_dir = workspace / "threads" / "active-thread"
    paused_dir = workspace / "threads" / "paused-thread"
    skills_dir.mkdir(parents=True)
    active_dir.mkdir(parents=True)
    paused_dir.mkdir(parents=True)
    _write_skill(
        skills_dir,
        "notes",
        """---
name: notes
description: Plain note helper
---""",
    )
    (active_dir / "STATE.md").write_text(
        "# Active Thread\nStatus: active\n\n## Goal\nKeep moving.\n",
        encoding="utf-8",
    )
    (paused_dir / "STATE.md").write_text(
        "# Paused Thread\nStatus: paused\n\n## Goal\nWait for input.\n",
        encoding="utf-8",
    )
    (active_dir / "THREAD.yaml").write_text(
        "related_threads:\n  - paused-thread\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/true")

    registry = ContextRegistry.from_workspace(
        workspace=workspace,
        skills_loader=SkillsLoader(workspace),
        max_thread_registry_size=20,
    )

    units = registry.context_units()

    assert units[0].key == "active-thread"
    assert registry.related_unit_keys("active-thread") == ("paused-thread",)
    assert registry.related_unit_keys("notes") == ()


def test_registry_expand_related_thread_slugs_respects_hop_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "ws"
    skills_dir = workspace / "skills"
    thread_a = workspace / "threads" / "thread-a"
    thread_b = workspace / "threads" / "thread-b"
    thread_c = workspace / "threads" / "thread-c"
    skills_dir.mkdir(parents=True)
    thread_a.mkdir(parents=True)
    thread_b.mkdir(parents=True)
    thread_c.mkdir(parents=True)
    _write_skill(
        skills_dir,
        "notes",
        """---
name: notes
description: Plain note helper
---""",
    )
    (thread_a / "STATE.md").write_text(
        "# Thread A\nStatus: active\n\n## Goal\nA goal.\n",
        encoding="utf-8",
    )
    (thread_b / "STATE.md").write_text(
        "# Thread B\nStatus: active\n\n## Goal\nB goal.\n",
        encoding="utf-8",
    )
    (thread_c / "STATE.md").write_text(
        "# Thread C\nStatus: active\n\n## Goal\nC goal.\n",
        encoding="utf-8",
    )
    (thread_a / "THREAD.yaml").write_text("related_threads:\n  - thread-b\n", encoding="utf-8")
    (thread_b / "THREAD.yaml").write_text("related_threads:\n  - thread-c\n", encoding="utf-8")
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/true")

    one_hop = ContextRegistry.from_workspace(
        workspace=workspace,
        skills_loader=SkillsLoader(workspace),
        max_thread_registry_size=20,
        related_thread_hops=1,
    )
    two_hop = ContextRegistry.from_workspace(
        workspace=workspace,
        skills_loader=SkillsLoader(workspace),
        max_thread_registry_size=20,
        related_thread_hops=2,
    )

    assert one_hop.expand_related_thread_slugs({"thread-a"}) == {"thread-a", "thread-b"}
    assert two_hop.expand_related_thread_slugs({"thread-a"}) == {
        "thread-a",
        "thread-b",
        "thread-c",
    }
