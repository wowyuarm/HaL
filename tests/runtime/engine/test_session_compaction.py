from __future__ import annotations

from hal.runtime.engine.session_compaction import (
    build_fallback_checkpoint,
    estimate_history_tokens,
    normalize_checkpoint,
    render_history_for_compaction,
)
from hal.runtime.session import _SESSION_COMPACTION_PROMPT


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
                        "function": {"name": "fs", "arguments": '{"path":"threads/x/BRIEF.md"}'},
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
                        "function": {"name": "fs", "arguments": '{"path":"threads/x/BRIEF.md"}'},
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
    assert "5 older messages" in text
    assert "1200" in text


def test_normalize_checkpoint_strips_analysis_tags() -> None:
    raw = "<analysis>\nthinking...\n</analysis>\n[Session Checkpoint]\n\n## Work done\n- stuff"
    result = normalize_checkpoint(raw)
    assert "<analysis>" not in result
    assert "[Session Checkpoint]" in result
    assert "## Work done" in result


def test_session_compaction_prompt_emphasizes_full_history_and_user_quotes() -> None:
    assert "full-history compaction" in _SESSION_COMPACTION_PROMPT
    assert "All User Messages (Non-tool)" in _SESSION_COMPACTION_PROMPT
    assert "Include short direct quotes" in _SESSION_COMPACTION_PROMPT
