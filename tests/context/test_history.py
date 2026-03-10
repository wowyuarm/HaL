from __future__ import annotations

from hal.context.message_building import build_session_baseline_message
from hal.runtime.session import build_persisted_session_history


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
