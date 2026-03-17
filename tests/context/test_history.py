from __future__ import annotations

from hal.runtime.session import build_persisted_session_history


def test_build_persisted_session_history_keeps_replayable_injects() -> None:
    working_set_messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "[HaL Turn Context]\nkind: turn_context\nsource: engine"},
        {"role": "user", "content": "current"},
    ]

    history = build_persisted_session_history(
        working_set_messages=working_set_messages,
        final_content="done",
        include_final_assistant=True,
    )

    assert history == [
        {"role": "user", "content": "[HaL Turn Context]\nkind: turn_context\nsource: engine"},
        {"role": "user", "content": "current"},
        {"role": "assistant", "content": "done"},
    ]
