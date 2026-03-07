from __future__ import annotations

from hal.context.prompt_layers import build_capabilities_prompt


def test_build_capabilities_prompt_joins_non_empty_sections() -> None:
    text = build_capabilities_prompt(
        always_skills_content="### Skill: notes\n\nBody",
        skills_summary="<skills></skills>",
        thread_summary="# Threads\n- t [active]",
    )

    assert "# Active Skills" in text
    assert "<skills></skills>" in text
    assert "# Threads" in text
    assert "\n\n---\n\n" in text


def test_build_capabilities_prompt_skips_empty_inputs() -> None:
    text = build_capabilities_prompt(
        always_skills_content="",
        skills_summary="",
        thread_summary="",
    )

    assert text == ""
