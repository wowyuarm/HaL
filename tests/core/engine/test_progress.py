"""Tests for progress message formatting helpers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hal.core.engine.progress import (
    _compose_progress_message,
    _extract_progress_text,
    _format_tool_hints,
)


def _tool_call(name: str, arguments: dict) -> SimpleNamespace:
    return SimpleNamespace(name=name, arguments=arguments)


def test_extract_progress_text_strips_think_block() -> None:
    content = "<think>hidden</think>\n我先检查目录"
    assert _extract_progress_text(content) == "我先检查目录"


def test_format_tool_hints_builds_hint_lines() -> None:
    calls = [_tool_call("fs", {"action": "list", "path": "."})]
    hints = _format_tool_hints(calls)
    assert hints == ["↳ fs('.')"]


@pytest.mark.parametrize(
    ("send_progress", "send_tool_hints", "expected"),
    [
        (False, False, None),
        (True, False, "progress"),
        (False, True, "↳ fs('.')"),
        (True, True, "progress\n↳ fs('.')"),
    ],
)
def test_compose_progress_message_policy_matrix(
    send_progress: bool, send_tool_hints: bool, expected: str | None
) -> None:
    actual = _compose_progress_message(
        "progress",
        ["↳ fs('.')"],
        send_progress=send_progress,
        send_tool_hints=send_tool_hints,
    )
    assert actual == expected
