from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from hal.context.history import (
    build_history_window,
    build_persisted_session_history,
    load_history_for_context,
)
from hal.context.message_building import build_session_baseline_message


def test_load_history_for_context_prefers_session_history() -> None:
    loaded = load_history_for_context(
        session_history=[{"role": "assistant", "content": "cached"}],
        memory=MagicMock(),
        history_config=SimpleNamespace(),
        channel="telegram",
        chat_id="1",
        token_model="test-model",
    )

    assert loaded.using_session_history is True
    assert loaded.messages == [{"role": "assistant", "content": "cached"}]
    assert loaded.history_window == []


def test_load_history_for_context_reads_memory_history_and_window(tmp_path: Path) -> None:
    daily_dir = tmp_path / "logs"
    daily_dir.mkdir(parents=True)
    today_file = daily_dir / "2026-03-06.jsonl"
    today_file.write_text('{"role":"user","content":"hello"}\n', encoding="utf-8")

    memory = MagicMock()
    memory.get_conversation_history.return_value = [{"role": "user", "content": "older"}]
    memory.daily_log = SimpleNamespace(data_dir=daily_dir)
    history_config = SimpleNamespace(
        max_messages=20,
        recent_full_turns=2,
        assistant_truncate_tokens=40,
        max_history_tokens=1000,
        history_days=1,
    )

    loaded = load_history_for_context(
        session_history=None,
        memory=memory,
        history_config=history_config,
        channel="telegram",
        chat_id="1",
        token_model="test-model",
    )

    assert loaded.using_session_history is False
    assert loaded.messages == [{"role": "user", "content": "older"}]
    assert loaded.history_window == build_history_window(history_days=1, log_dir=daily_dir)


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
