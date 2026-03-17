from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from hal.context.compiler import ContextCompiler, SessionTurnRequest
from hal.context.message_injects import KIND_TURN_CONTEXT
from hal.context.recall import collect_active_thread_slugs, collect_recalled_thread_slugs


@pytest.fixture()
def builder() -> MagicMock:
    builder = MagicMock()
    builder.build_messages.return_value = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
    ]
    return builder


@pytest.fixture()
def context_registry() -> MagicMock:
    registry = MagicMock()
    registry.related_thread_hops = 1
    registry.thread_snapshot.return_value = []
    registry.active_thread_entry_snapshot.return_value = []
    registry.related_unit_keys.return_value = ()
    return registry


async def test_compile_session_turn_appends_turn_context_inject(
    builder: MagicMock,
    context_registry: MagicMock,
) -> None:
    memory_search = AsyncMock()
    memory_search.search.return_value = [
        SimpleNamespace(
            thread="github-actions",
            source="episodes/auth/e1.md",
            heading="Recent progress",
            content="episode",
            score=1.0,
            source_type="raw",
        )
    ]
    compiler = ContextCompiler(
        context_builder=builder,
        context_registry=context_registry,
        memory_search=memory_search,
        auto_inject_top_k=3,
        recall_min_score=0.0,
    )

    compiled = await compiler.compile_session_turn(
        SessionTurnRequest(
            history=[],
            current_message="continue",
            media=None,
            channel="telegram",
            chat_id="c1",
            token_model="test-model",
            memory_budget_tokens=100,
            recall_max_total_tokens=500,
            recall_max_per_item_tokens=125,
            mounted_threads=None,
        )
    )

    assert compiled.recalled_thread_slugs == {"github-actions"}
    assert compiled.scope_thread_slugs == set()
    assert len(compiled.injected_messages) == 1
    assert compiled.injected_messages[0].kind == KIND_TURN_CONTEXT
    assert "[HaL Turn Context]" in compiled.injected_messages[0].content
    assert "<relevant_memories>" in compiled.injected_messages[0].content
    memory_search.search.assert_awaited_once_with("continue", top_k=3, min_score=0.0)
    builder.build_messages.assert_called_once()
    assert (
        builder.build_messages.call_args.kwargs["history"][-1]["content"]
        == compiled.injected_messages[0].content
    )


async def test_compile_session_turn_preserves_existing_history_and_scope_threads(
    builder: MagicMock,
    context_registry: MagicMock,
) -> None:
    memory_search = AsyncMock()
    memory_search.search.return_value = []
    compiler = ContextCompiler(
        context_builder=builder,
        context_registry=context_registry,
        memory_search=memory_search,
        auto_inject_top_k=3,
        recall_min_score=0.0,
    )

    prior_history = [{"role": "assistant", "content": "older"}]
    compiled = await compiler.compile_session_turn(
        SessionTurnRequest(
            history=prior_history,
            current_message="continue",
            media=None,
            channel="telegram",
            chat_id="c1",
            token_model="test-model",
            memory_budget_tokens=100,
            recall_max_total_tokens=500,
            recall_max_per_item_tokens=125,
            mounted_threads={"github-actions"},
        )
    )

    assert compiled.scope_thread_slugs == {"github-actions"}
    assert compiled.recalled_thread_slugs == set()
    builder.build_messages.assert_called_once()
    history = builder.build_messages.call_args.kwargs["history"]
    assert history[0] == prior_history[0]
    assert history[-1]["content"] == compiled.injected_messages[0].content
    assert "scope: github-actions" in compiled.injected_messages[0].content


def test_collect_recalled_thread_slugs_ignores_empty_values() -> None:
    results = [
        SimpleNamespace(thread="github-actions"),
        SimpleNamespace(thread=""),
        SimpleNamespace(thread="  "),
        SimpleNamespace(thread="hal-architecture"),
    ]
    assert collect_recalled_thread_slugs(results) == {"github-actions", "hal-architecture"}


def test_collect_active_thread_slugs_filters_for_active_status() -> None:
    snapshot = [
        {"slug": "github-actions", "status": "active"},
        {"slug": "blog", "status": "paused"},
        {"slug": "hal-architecture", "status": "active"},
    ]
    assert collect_active_thread_slugs(snapshot) == {"github-actions", "hal-architecture"}
