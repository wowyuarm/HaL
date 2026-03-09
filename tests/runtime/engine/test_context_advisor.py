from __future__ import annotations

from unittest.mock import AsyncMock

from hal.runtime.engine.context_advisor import (
    ContextAdvisorSuggestion,
    build_context_advisor_input,
    build_context_advisor_messages,
    build_context_hint_keys,
    build_context_hint_text,
    build_thread_path_map,
    filter_context_advisor_suggestion,
    has_substantive_tool_calls,
    parse_context_advisor_output,
    request_context_advisor_suggestion,
)


class _ToolCall:
    def __init__(self, name: str, arguments: dict):
        self.name = name
        self.arguments = arguments


def test_has_substantive_tool_calls() -> None:
    assert not has_substantive_tool_calls([_ToolCall("message", {"content": "x"})])
    assert has_substantive_tool_calls([_ToolCall("fs", {"action": "read"})])


def test_parse_context_advisor_output_json_and_code_fence() -> None:
    parsed = parse_context_advisor_output('{"skills":["git"],"threads":["t1"],"reason":"r"}')
    assert parsed is not None
    assert parsed.skills == ["git"]
    assert parsed.threads == ["t1"]

    parsed2 = parse_context_advisor_output(
        """```json
{"skills":["s1"],"threads":[],"reason":"ok"}
```"""
    )
    assert parsed2 is not None
    assert parsed2.skills == ["s1"]


def test_build_context_hint_text() -> None:
    hint = build_context_hint_text(
        ContextAdvisorSuggestion(
            skills=["skill-a"],
            threads=["thread-a"],
            reason="matches current task",
        ),
        thread_path_map={"thread-a": "threads/thread-a/BRIEF.md"},
    )
    assert "[Context Hint]" in hint
    assert "skill-a" in hint
    assert "threads/thread-a/BRIEF.md" in hint


def test_build_context_advisor_input_and_messages() -> None:
    advisor_input = build_context_advisor_input(
        latest_user_message="u" * 2100,
        assistant_content="a" * 2100,
        tool_calls=[_ToolCall("fs", {"action": "read"})],
        skill_registry=[{"name": "skill-a", "description": "d", "available": True}],
        thread_registry=[
            {
                "slug": "thread-a",
                "name": "Thread A",
                "status": "active",
                "description": "work",
                "state_path": "threads/thread-a/BRIEF.md",
            }
        ],
    )

    assert len(advisor_input.latest_user_message) == 2000
    assert len(advisor_input.assistant_progress) == 2000
    assert advisor_input.tool_calls == [{"name": "fs", "arguments": {"action": "read"}}]

    messages = build_context_advisor_messages(advisor_input)
    assert messages[0]["role"] == "system"
    assert "context advisor" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert "thread-a" in messages[1]["content"]


async def test_request_context_advisor_suggestion() -> None:
    chat = AsyncMock(
        return_value=type(
            "Resp", (), {"content": '{"skills":["git"],"threads":["t1"],"reason":"r"}'}
        )()
    )

    advisor_input = build_context_advisor_input(
        latest_user_message="do task",
        assistant_content="working",
        tool_calls=[_ToolCall("fs", {"action": "read"})],
        skill_registry=[],
        thread_registry=[],
    )
    suggestion = await request_context_advisor_suggestion(
        chat=chat,
        model="worker",
        advisor_input=advisor_input,
    )

    assert suggestion == ContextAdvisorSuggestion(skills=["git"], threads=["t1"], reason="r")
    chat.assert_awaited_once()


def test_build_context_hint_keys_and_filter_suggestion() -> None:
    suggestion = ContextAdvisorSuggestion(
        skills=["skill-a", "skill-b"],
        threads=["thread-a", "thread-b"],
        reason="matches current task",
    )

    keys = build_context_hint_keys(suggestion)
    assert keys == ["skill:skill-a", "skill:skill-b", "thread:thread-a", "thread:thread-b"]

    filtered = filter_context_advisor_suggestion(
        suggestion,
        allowed_keys={"skill:skill-b", "thread:thread-a"},
    )
    assert filtered == ContextAdvisorSuggestion(
        skills=["skill-b"],
        threads=["thread-a"],
        reason="matches current task",
    )


def test_build_thread_path_map() -> None:
    mapping = build_thread_path_map(
        [
            {"slug": "thread-a", "state_path": "threads/thread-a/BRIEF.md"},
            {"slug": "thread-b", "state_path": "threads/thread-b/BRIEF.md"},
        ]
    )
    assert mapping == {
        "thread-a": "threads/thread-a/BRIEF.md",
        "thread-b": "threads/thread-b/BRIEF.md",
    }
