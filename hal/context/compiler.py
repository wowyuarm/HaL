"""Session-scoped context compilation for working-set assembly."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from hal.context.message_injects import MessageInject, build_turn_context_inject
from hal.context.recall import collect_recalled_thread_slugs, prefetch_memory_results

if TYPE_CHECKING:
    from hal.context.builder import ContextBuilder
    from hal.context.registry import ContextRegistry
    from hal.memory.search import MemorySearch


@dataclass(slots=True)
class CompiledSessionContext:
    """Compiled working-set inputs for one turn."""

    messages: list[dict[str, object]]
    search_results: list[object]
    recalled_thread_slugs: set[str]
    scope_thread_slugs: set[str]
    injected_messages: list[MessageInject] = field(default_factory=list)


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
    mounted_threads: set[str] | None = None


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
        """Compile one session turn into prompt messages and replayable injects."""
        search_results = await prefetch_memory_results(
            memory_search=self._memory_search,
            current_message=request.current_message,
            top_k=self._auto_inject_top_k,
            min_score=self._recall_min_score,
        )
        recalled_thread_slugs = collect_recalled_thread_slugs(search_results)
        scope_thread_slugs = {slug for slug in (request.mounted_threads or set()) if slug}
        turn_context = build_turn_context_inject(
            channel=request.channel,
            chat_id=request.chat_id,
            mounted_threads=sorted(scope_thread_slugs),
            memory_search_results=search_results or None,
            recall_max_total_tokens=request.recall_max_total_tokens,
            recall_max_per_item_tokens=request.recall_max_per_item_tokens,
            token_model=request.token_model,
        )
        history = list(request.history)
        history.append(turn_context.as_history_message())
        messages = self._context_builder.build_messages(
            history=history,
            current_message=request.current_message,
            media=request.media,
            channel=request.channel,
            chat_id=request.chat_id,
            memory_budget_tokens=request.memory_budget_tokens,
            recall_max_total_tokens=request.recall_max_total_tokens,
            recall_max_per_item_tokens=request.recall_max_per_item_tokens,
            token_model=request.token_model,
            prepend_dynamic_context_to_current=False,
        )
        return CompiledSessionContext(
            messages=messages,
            search_results=search_results,
            recalled_thread_slugs=recalled_thread_slugs,
            scope_thread_slugs=scope_thread_slugs,
            injected_messages=[turn_context],
        )
