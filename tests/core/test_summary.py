"""Tests for summary prompt construction."""

from __future__ import annotations

from hal.core.runtime.loop import LoopMetadata
from hal.core.runtime.summary import _SUMMARY_SYSTEM_PROMPT, _build_summary_prompt


def test_summary_system_prompt_uses_structured_headers() -> None:
    assert "**Outcome**" in _SUMMARY_SYSTEM_PROMPT
    assert "**Files modified**" in _SUMMARY_SYSTEM_PROMPT
    assert "**Commands run**" in _SUMMARY_SYSTEM_PROMPT
    assert "**Open issues**" in _SUMMARY_SYSTEM_PROMPT
    assert "**Failed actions**" in _SUMMARY_SYSTEM_PROMPT


def test_build_summary_prompt_includes_metadata_and_final_response() -> None:
    meta = LoopMetadata(
        iterations=3,
        tools_used=["fs", "exec"],
        files_modified=["a.txt"],
        commands_run=["ls -la"],
        has_side_effects=True,
        loop_messages=[{"role": "assistant", "content": "Done"}],
    )

    prompt = _build_summary_prompt(meta, "final answer")
    assert "<metadata>" in prompt
    assert "iterations: 3" in prompt
    assert "tools_used: fs, exec" in prompt
    assert "files_modified: a.txt" in prompt
    assert "<final_response>" in prompt
    assert "final answer" in prompt
