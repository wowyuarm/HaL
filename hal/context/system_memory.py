"""Helpers for injecting system MEMORY.md into prompt context."""

from __future__ import annotations

from hal.context.token_budget import estimate_text_tokens, trim_text_to_token_budget
from hal.workspace.memory import SystemMemoryRepository


def build_system_memory_context(
    repository: SystemMemoryRepository,
    *,
    budget_tokens: int | None = None,
    token_model: str | None = None,
) -> str:
    """Build the prompt-ready system memory block from ``system/MEMORY.md``."""
    content = repository.read()
    if not content:
        return ""

    memory_block = f"## Long-term Memory\n\n{content}"
    if budget_tokens is None or budget_tokens <= 0:
        return memory_block
    if estimate_text_tokens(memory_block, model=token_model) <= budget_tokens:
        return memory_block

    return trim_text_to_token_budget(
        memory_block,
        budget_tokens,
        model=token_model,
        suffix="\n\n[...truncated]",
    )
