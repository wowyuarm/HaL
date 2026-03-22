from __future__ import annotations

from types import SimpleNamespace

from hal.context.dynamic_context import (
    build_dynamic_context_block,
    build_recall_entry,
    collect_recall_lines,
)
from hal.context.token_budget import estimate_text_tokens


def test_build_dynamic_context_block_renders_meta_threads_and_recall() -> None:
    text = build_dynamic_context_block(
        channel="telegram",
        chat_id="c1",
        active_threads=[
            {
                "name": "GitHub Actions",
                "state_path": "threads/github-actions/BRIEF.md",
                "state_content": "## Current State\n- Drafted workflow.",
            }
        ],
        active_threads_max_total_tokens=1000,
        active_thread_max_tokens=500,
        recall_results=[
            SimpleNamespace(
                source="episodes/workflow.md",
                heading="Decisions",
                score=1.0,
                source_type="episode",
                content="Use Claude for implementation and Codex for review.",
            )
        ],
        recall_max_total_tokens=500,
        recall_max_per_item_tokens=125,
        token_model="test-model",
    )

    assert "<channel>telegram</channel>" in text
    assert "<chat_id>c1</chat_id>" in text
    assert "<active_threads>" in text
    assert "threads/github-actions/BRIEF.md" in text
    assert "<relevant_memories>" in text
    assert "episodes/workflow.md" in text


def test_build_dynamic_context_block_limits_active_thread_states_by_budget() -> None:
    text = build_dynamic_context_block(
        channel="telegram",
        chat_id="c1",
        active_threads=[
            {
                "name": "Thread High",
                "state_path": "threads/high/BRIEF.md",
                "state_content": "A " * 400,
            },
            {
                "name": "Thread Low",
                "state_path": "threads/low/BRIEF.md",
                "state_content": "B " * 400,
            },
        ],
        active_threads_max_total_tokens=80,
        active_thread_max_tokens=40,
        recall_results=None,
        recall_max_total_tokens=500,
        recall_max_per_item_tokens=125,
        token_model="test-model",
    )

    assert "threads/high/BRIEF.md" in text
    assert "threads/low/BRIEF.md" not in text


def test_collect_recall_lines_respects_total_budget() -> None:
    results = [
        SimpleNamespace(
            source="one.md",
            heading="H1",
            score=1.0,
            source_type="episode",
            content="x " * 50,
        ),
        SimpleNamespace(
            source="two.md",
            heading="H2",
            score=0.9,
            source_type="episode",
            content="y " * 50,
        ),
    ]
    first_entry = build_recall_entry(results[0], per_item_limit=10, token_model="test-model")
    budget = estimate_text_tokens(first_entry, model="test-model")

    lines = collect_recall_lines(
        recall_results=results,
        recall_max_total_tokens=budget,
        recall_max_per_item_tokens=10,
        token_model="test-model",
    )

    assert len(lines) == 1
    assert "one.md" in lines[0]
