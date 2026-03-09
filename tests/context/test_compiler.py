from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from hal.context.baseline import collect_active_thread_slugs, collect_recalled_thread_slugs
from hal.context.compiler import ContextCompiler, SessionTurnRequest


@pytest.fixture()
def builder() -> MagicMock:
    builder = MagicMock()
    builder.baseline_max_active_threads = 3
    builder.build_dynamic_context_block.return_value = "<context>ctx</context>"
    builder.build_messages.return_value = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
    ]
    return builder


@pytest.fixture()
def context_registry() -> MagicMock:
    registry = MagicMock()
    registry.related_thread_hops = 1
    registry.thread_snapshot.return_value = [
        {
            "slug": "github-actions",
            "name": "GitHub Actions",
            "status": "active",
            "description": "workflow work",
            "state_path": "threads/github-actions/BRIEF.md",
        }
    ]
    registry.active_thread_entry_snapshot.return_value = [
        {
            "slug": "github-actions",
            "name": "GitHub Actions",
            "status": "active",
            "description": "workflow work",
            "state_path": "threads/github-actions/BRIEF.md",
            "state_content": "## Current State\n- Drafted workflow.",
            "priority": 200,
            "related_threads": (),
        }
    ]
    registry.related_unit_keys.return_value = ()
    return registry


async def test_compile_session_turn_builds_new_baseline(
    builder: MagicMock,
    context_registry: MagicMock,
) -> None:
    memory_search = AsyncMock()
    memory_search.search.return_value = [
        SimpleNamespace(thread="github-actions", content="episode", score=1.0)
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
            existing_baseline=None,
        )
    )

    assert compiled.baseline_created is True
    assert compiled.session_baseline == "<context>ctx</context>"
    assert compiled.recalled_thread_slugs == {"github-actions"}
    assert compiled.baseline_thread_slugs == {"github-actions"}
    memory_search.search.assert_awaited_once()
    builder.build_dynamic_context_block.assert_called_once()
    builder.build_messages.assert_called_once()


async def test_compile_session_turn_reuses_existing_baseline(
    builder: MagicMock,
    context_registry: MagicMock,
) -> None:
    memory_search = AsyncMock()
    compiler = ContextCompiler(
        context_builder=builder,
        context_registry=context_registry,
        memory_search=memory_search,
        auto_inject_top_k=3,
        recall_min_score=0.0,
    )

    compiled = await compiler.compile_session_turn(
        SessionTurnRequest(
            history=[{"role": "assistant", "content": "older"}],
            current_message="continue",
            media=None,
            channel="telegram",
            chat_id="c1",
            token_model="test-model",
            memory_budget_tokens=100,
            recall_max_total_tokens=500,
            recall_max_per_item_tokens=125,
            existing_baseline="<context>frozen</context>",
        )
    )

    assert compiled.baseline_created is False
    assert compiled.session_baseline == "<context>frozen</context>"
    assert compiled.search_results == []
    assert compiled.recalled_thread_slugs == set()
    memory_search.search.assert_not_called()
    builder.build_dynamic_context_block.assert_not_called()
    builder.build_messages.assert_called_once()


async def test_compile_session_turn_selects_related_active_threads_for_baseline(
    builder: MagicMock,
) -> None:
    context_registry = MagicMock()
    context_registry.related_thread_hops = 1
    context_registry.thread_snapshot.return_value = [
        {
            "slug": "github-actions",
            "name": "GitHub Actions",
            "status": "active",
            "description": "workflow work",
            "state_path": "threads/github-actions/BRIEF.md",
        },
        {
            "slug": "hal-architecture",
            "name": "HaL Architecture",
            "status": "active",
            "description": "kernel work",
            "state_path": "threads/hal-architecture/BRIEF.md",
        },
        {
            "slug": "blog",
            "name": "Blog",
            "status": "active",
            "description": "content work",
            "state_path": "threads/blog/BRIEF.md",
        },
    ]
    context_registry.active_thread_entry_snapshot.return_value = [
        {
            "slug": "github-actions",
            "name": "GitHub Actions",
            "status": "active",
            "description": "workflow work",
            "state_path": "threads/github-actions/BRIEF.md",
            "state_content": "workflow",
            "priority": 200,
            "related_threads": ("hal-architecture",),
        },
        {
            "slug": "hal-architecture",
            "name": "HaL Architecture",
            "status": "active",
            "description": "kernel work",
            "state_path": "threads/hal-architecture/BRIEF.md",
            "state_content": "architecture",
            "priority": 200,
            "related_threads": (),
        },
        {
            "slug": "blog",
            "name": "Blog",
            "status": "active",
            "description": "content work",
            "state_path": "threads/blog/BRIEF.md",
            "state_content": "blog",
            "priority": 200,
            "related_threads": (),
        },
    ]
    context_registry.related_unit_keys.side_effect = lambda key: (
        ("hal-architecture",) if key == "github-actions" else ()
    )
    memory_search = AsyncMock()
    memory_search.search.return_value = [
        SimpleNamespace(thread="github-actions", content="episode", score=1.0)
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
            current_message="continue github actions",
            media=None,
            channel="telegram",
            chat_id="c1",
            token_model="test-model",
            memory_budget_tokens=100,
            recall_max_total_tokens=500,
            recall_max_per_item_tokens=125,
            existing_baseline=None,
        )
    )

    baseline_active_threads = builder.build_dynamic_context_block.call_args.kwargs["active_threads"]
    assert [entry["slug"] for entry in baseline_active_threads] == [
        "github-actions",
        "hal-architecture",
    ]
    assert compiled.baseline_thread_slugs == {"github-actions", "hal-architecture"}


async def test_compile_session_turn_caps_baseline_active_threads_by_priority(
    builder: MagicMock,
) -> None:
    builder.baseline_max_active_threads = 2
    context_registry = MagicMock()
    context_registry.related_thread_hops = 1
    context_registry.thread_snapshot.return_value = [
        {
            "slug": "thread-low",
            "name": "Low",
            "status": "active",
            "description": "low",
            "state_path": "threads/thread-low/BRIEF.md",
        },
        {
            "slug": "thread-high",
            "name": "High",
            "status": "active",
            "description": "high",
            "state_path": "threads/thread-high/BRIEF.md",
        },
        {
            "slug": "thread-mid",
            "name": "Mid",
            "status": "active",
            "description": "mid",
            "state_path": "threads/thread-mid/BRIEF.md",
        },
    ]
    context_registry.active_thread_entry_snapshot.return_value = [
        {
            "slug": "thread-low",
            "name": "Low",
            "status": "active",
            "description": "low",
            "state_path": "threads/thread-low/BRIEF.md",
            "state_content": "low",
            "priority": 200,
            "related_threads": (),
            "mtime": 100,
        },
        {
            "slug": "thread-high",
            "name": "High",
            "status": "active",
            "description": "high",
            "state_path": "threads/thread-high/BRIEF.md",
            "state_content": "high",
            "priority": 260,
            "related_threads": (),
            "mtime": 300,
        },
        {
            "slug": "thread-mid",
            "name": "Mid",
            "status": "active",
            "description": "mid",
            "state_path": "threads/thread-mid/BRIEF.md",
            "state_content": "mid",
            "priority": 230,
            "related_threads": (),
            "mtime": 200,
        },
    ]
    context_registry.related_unit_keys.return_value = ()

    memory_search = AsyncMock()
    memory_search.search.return_value = []
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
            existing_baseline=None,
        )
    )

    baseline_active_threads = builder.build_dynamic_context_block.call_args.kwargs["active_threads"]
    assert [entry["slug"] for entry in baseline_active_threads] == ["thread-high", "thread-mid"]
    assert compiled.baseline_thread_slugs == {"thread-high", "thread-mid"}


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
