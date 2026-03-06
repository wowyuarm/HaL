"""Session-scoped context compilation for working-set assembly."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from hal.core.context.baseline import compile_baseline_plan

if TYPE_CHECKING:
    from hal.core.context.builder import ContextBuilder
    from hal.core.context.registry import ContextRegistry
    from hal.core.memory.search import MemorySearch


@dataclass(slots=True)
class CompiledSessionContext:
    """Compiled working-set inputs for one turn."""

    messages: list[dict[str, object]]
    session_baseline: str
    search_results: list[object]
    recalled_thread_slugs: set[str]
    baseline_thread_slugs: set[str]
    baseline_created: bool


@dataclass(frozen=True, slots=True)
class SessionTurnRequest:
    """Input payload for compiling one session turn into a working set."""

    history: list[dict[str, object]]
    current_message: str
    media: list[str] | None
    channel: str | None
    chat_id: str | None
    token_model: str | None
    memory_budget_tokens: int | None
    recall_max_total_tokens: int
    recall_max_per_item_tokens: int
    existing_baseline: str | None


class ContextCompiler:
    """Compile session working sets from registries, memory recall, and history."""

    def __init__(
        self,
        *,
        context_builder: "ContextBuilder",
        context_registry: "ContextRegistry",
        memory_search: "MemorySearch | None" = None,
        auto_inject_top_k: int = 3,
        recall_min_score: float = 0.0,
    ) -> None:
        self._context_builder = context_builder
        self._context_registry = context_registry
        self._memory_search = memory_search
        self._auto_inject_top_k = auto_inject_top_k
        self._recall_min_score = recall_min_score

    def set_memory_search(self, memory_search: "MemorySearch | None") -> None:
        """Update the memory search dependency after engine construction changes."""
        self._memory_search = memory_search

    async def compile_session_turn(
        self,
        request: SessionTurnRequest,
    ) -> CompiledSessionContext:
        """Compile one session turn into prompt messages and baseline metadata."""
        baseline = await compile_baseline_plan(
            context_builder=self._context_builder,
            current_message=request.current_message,
            channel=request.channel,
            chat_id=request.chat_id,
            token_model=request.token_model,
            recall_max_total_tokens=request.recall_max_total_tokens,
            recall_max_per_item_tokens=request.recall_max_per_item_tokens,
            existing_baseline=request.existing_baseline,
            memory_search=self._memory_search,
            auto_inject_top_k=self._auto_inject_top_k,
            recall_min_score=self._recall_min_score,
            thread_snapshot=self._context_registry.thread_snapshot(),
            active_thread_entries=self._context_registry.active_thread_entry_snapshot(),
            related_lookup=self._context_registry.related_unit_keys,
            related_hops=self._context_registry.related_thread_hops,
            max_active_threads=_resolve_baseline_active_thread_limit(self._context_builder),
        )
        messages = self._context_builder.build_messages(
            history=request.history,
            current_message=request.current_message,
            media=request.media,
            channel=request.channel,
            chat_id=request.chat_id,
            memory_search_results=baseline.search_results or None,
            memory_budget_tokens=request.memory_budget_tokens,
            recall_max_total_tokens=request.recall_max_total_tokens,
            recall_max_per_item_tokens=request.recall_max_per_item_tokens,
            token_model=request.token_model,
            session_baseline=baseline.session_baseline,
            prepend_dynamic_context_to_current=False,
        )
        return CompiledSessionContext(
            messages=messages,
            session_baseline=baseline.session_baseline,
            search_results=baseline.search_results,
            recalled_thread_slugs=baseline.recalled_thread_slugs,
            baseline_thread_slugs=baseline.baseline_thread_slugs,
            baseline_created=baseline.baseline_created,
        )


def _resolve_baseline_active_thread_limit(context_builder: object) -> int:
    """Resolve baseline active-thread cap from context builder with test-safe fallback."""
    raw = getattr(context_builder, "baseline_max_active_threads", 0)
    if isinstance(raw, int):
        return max(raw, 0)
    try:
        return max(int(str(raw)), 0)
    except Exception:
        return 0
