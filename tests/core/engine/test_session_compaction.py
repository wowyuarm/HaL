from __future__ import annotations

from hal.core.engine.session_compaction import (
    build_fallback_checkpoint,
    estimate_history_tokens,
    normalize_checkpoint,
    render_history_for_compaction,
    split_history_for_compaction,
)


def test_split_history_for_compaction_keeps_recent_user_turns() -> None:
    history = [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "u3"},
        {"role": "assistant", "content": "a3"},
    ]
    older, tail = split_history_for_compaction(history, keep_recent_user_turns=1)
    assert [m["content"] for m in older] == ["u1", "a1", "u2", "a2"]
    assert [m["content"] for m in tail] == ["u3", "a3"]


def test_normalize_checkpoint_adds_header() -> None:
    normalized = normalize_checkpoint("## Decisions\n- keep")
    assert normalized.startswith("[Session Checkpoint]")


def test_estimate_history_tokens_nonzero() -> None:
    tokens = estimate_history_tokens(
        [{"role": "user", "content": "hello world"}],
        model=None,
    )
    assert tokens > 0


def test_estimate_history_tokens_includes_tool_calls_and_reasoning() -> None:
    tokens = estimate_history_tokens(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "tc_1",
                        "type": "function",
                        "function": {"name": "fs", "arguments": '{"path":"threads/x/STATE.md"}'},
                    }
                ],
                "reasoning_content": "Need to inspect the active thread state before editing.",
            }
        ],
        model=None,
    )
    assert tokens > 20


def test_render_history_for_compaction_includes_roles() -> None:
    rendered = render_history_for_compaction(
        [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
    )
    assert "[1] user" in rendered
    assert "[2] assistant" in rendered


def test_render_history_for_compaction_includes_tool_calls_and_reasoning() -> None:
    rendered = render_history_for_compaction(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "tc_1",
                        "type": "function",
                        "function": {"name": "fs", "arguments": '{"path":"threads/x/STATE.md"}'},
                    }
                ],
                "reasoning_content": "Need more context first.",
            }
        ]
    )
    assert "tool_call: fs(" in rendered
    assert "reasoning: Need more context first." in rendered


def test_build_fallback_checkpoint_contains_summary_fields() -> None:
    text = build_fallback_checkpoint(compacted_messages=5, compacted_tokens=1200)
    assert "[Session Checkpoint]" in text
    assert "## Decisions" in text
    assert "## Open Items" in text
