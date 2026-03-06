from __future__ import annotations

from pathlib import Path

from hal.workspace.memory import MemoryRepository


def test_memory_repository_reads_writes_and_updates_sections(tmp_path: Path) -> None:
    repo = MemoryRepository(tmp_path)

    repo.update("# Memory\n\n## Preferences\nLikes concise replies.\n")

    assert repo.path == tmp_path / "memory" / "MEMORY.md"
    assert repo.read().startswith("# Memory")
    assert repo.get_section("Preferences") == "Likes concise replies."

    repo.update_section("Preferences", "Likes structured replies.")
    repo.update_section("Projects", "HaL context system")

    content = repo.read()
    assert "Likes structured replies." in content
    assert "## Projects\nHaL context system" in content
