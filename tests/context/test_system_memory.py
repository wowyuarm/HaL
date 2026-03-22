from __future__ import annotations

from pathlib import Path

from hal.context.system_memory import build_system_memory_context
from hal.context.token_budget import estimate_text_tokens
from hal.workspace.memory import SystemMemoryRepository


def test_build_system_memory_context_returns_empty_for_missing_file(tmp_path: Path) -> None:
    repository = SystemMemoryRepository(tmp_path / "missing" / "MEMORY.md")
    assert build_system_memory_context(repository) == ""


def test_build_system_memory_context_includes_long_term_heading(tmp_path: Path) -> None:
    repository = SystemMemoryRepository(tmp_path / "system" / "MEMORY.md")
    repository.update("## Knowledge\nImportant fact.\n")

    context = build_system_memory_context(repository)

    assert "Long-term Memory" in context
    assert "Important fact." in context


def test_build_system_memory_context_respects_token_budget(tmp_path: Path) -> None:
    repository = SystemMemoryRepository(tmp_path / "system" / "MEMORY.md")
    repository.update("A" * 200)

    context = build_system_memory_context(repository, budget_tokens=20)

    assert estimate_text_tokens(context) <= 20
    assert "[...truncated]" in context
