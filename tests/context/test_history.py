from __future__ import annotations

from unittest.mock import MagicMock

from hal.context.history import (
    build_persisted_session_history,
    load_history_for_context,
)
from hal.context.message_building import build_session_baseline_message


def test_load_history_for_context_uses_session_history() -> None:
    loaded = load_history_for_context(
        session_history=[{"role": "assistant", "content": "cached"}],
    )

    assert loaded.using_session_history is True
    assert loaded.messages == [{"role": "assistant", "content": "cached"}]


def test_load_history_for_context_empty_when_no_session() -> None:
    loaded = load_history_for_context(session_history=None)

    assert loaded.using_session_history is False
    assert loaded.messages == []


def test_load_history_for_context_absorbs_extra_kwargs() -> None:
    """Legacy callers may pass extra kwargs (memory, history_config, etc)."""
    loaded = load_history_for_context(
        session_history=[{"role": "user", "content": "hi"}],
        memory=MagicMock(),
        channel="telegram",
        chat_id="1",
    )
    assert loaded.using_session_history is True
    assert len(loaded.messages) == 1


def test_build_persisted_session_history_strips_session_baseline() -> None:
    working_set_messages = [
        {"role": "system", "content": "sys"},
        build_session_baseline_message("<context>baseline</context>"),
        {"role": "user", "content": "current"},
    ]

    history = build_persisted_session_history(
        working_set_messages=working_set_messages,
        final_content="done",
        include_final_assistant=True,
    )

    assert history == [
        {"role": "user", "content": "current"},
        {"role": "assistant", "content": "done"},
    ]
