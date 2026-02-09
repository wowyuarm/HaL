"""Tests for hal.core.context.compiler — ContextCompiler."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from hal.core.context.compiler import ContextCompiler

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """Create a minimal workspace directory with memory/ sub-dir."""
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    return tmp_path


@pytest.fixture()
def compiler(workspace: Path) -> ContextCompiler:
    """ContextCompiler with mocked SkillsLoader (no real skills on disk)."""
    with patch("hal.core.context.compiler.SkillsLoader") as mock_skills_cls:
        loader = MagicMock()
        loader.get_always_skills.return_value = []
        loader.build_skills_summary.return_value = ""
        mock_skills_cls.return_value = loader
        cc = ContextCompiler(workspace)
    return cc


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestInit:
    def test_workspace_is_stored(self, workspace: Path) -> None:
        with patch("hal.core.context.compiler.SkillsLoader"):
            cc = ContextCompiler(workspace)
        assert cc.workspace == workspace

    def test_memory_manager_defaults_to_none(self, compiler: ContextCompiler) -> None:
        assert compiler._memory_manager is None

    def test_memory_manager_stored_when_provided(self, workspace: Path) -> None:
        mm = MagicMock()
        with patch("hal.core.context.compiler.SkillsLoader"):
            cc = ContextCompiler(workspace, memory_manager=mm)
        assert cc._memory_manager is mm


# ---------------------------------------------------------------------------
# Bootstrap files loading
# ---------------------------------------------------------------------------


class TestBootstrapFiles:
    def test_loads_existing_bootstrap_files(self, workspace: Path) -> None:
        (workspace / "SOUL.md").write_text("Be helpful.", encoding="utf-8")
        (workspace / "IDENTITY.md").write_text("I am HaL.", encoding="utf-8")

        with patch("hal.core.context.compiler.SkillsLoader") as cls:
            cls.return_value = MagicMock(
                get_always_skills=MagicMock(return_value=[]),
                build_skills_summary=MagicMock(return_value=""),
            )
            cc = ContextCompiler(workspace)

        prompt = cc.build_system_prompt()
        assert "Be helpful." in prompt
        assert "I am HaL." in prompt

    def test_ignores_missing_bootstrap_files(self, compiler: ContextCompiler) -> None:
        # No bootstrap files on disk — should not raise
        prompt = compiler.build_system_prompt()
        assert "HaL" in prompt



# ---------------------------------------------------------------------------
# build_system_prompt()
# ---------------------------------------------------------------------------


class TestBuildSystemPrompt:
    def test_contains_hal_name(self, compiler: ContextCompiler) -> None:
        prompt = compiler.build_system_prompt()
        assert "HaL" in prompt

    def test_contains_workspace_path(self, compiler: ContextCompiler, workspace: Path) -> None:
        prompt = compiler.build_system_prompt()
        resolved = str(workspace.expanduser().resolve())
        assert resolved in prompt

    def test_includes_memory_from_manager(self, workspace: Path) -> None:
        mm = MagicMock()
        mm.get_context.return_value = "Remember: user likes tea."

        with patch("hal.core.context.compiler.SkillsLoader") as cls:
            cls.return_value = MagicMock(
                get_always_skills=MagicMock(return_value=[]),
                build_skills_summary=MagicMock(return_value=""),
            )
            cc = ContextCompiler(workspace, memory_manager=mm)

        prompt = cc.build_system_prompt()
        assert "Remember: user likes tea." in prompt
        assert "# Memory" in prompt

    def test_falls_back_to_legacy_memory(self, workspace: Path) -> None:
        # Write a long-term memory file so legacy store returns it
        (workspace / "memory" / "MEMORY.md").write_text("Legacy memory content", encoding="utf-8")

        with patch("hal.core.context.compiler.SkillsLoader") as cls:
            cls.return_value = MagicMock(
                get_always_skills=MagicMock(return_value=[]),
                build_skills_summary=MagicMock(return_value=""),
            )
            cc = ContextCompiler(workspace)

        prompt = cc.build_system_prompt()
        assert "Legacy memory content" in prompt

    def test_no_memory_section_when_empty(self, compiler: ContextCompiler) -> None:
        prompt = compiler.build_system_prompt()
        assert "# Memory" not in prompt

    def test_layers_separated_by_divider(self, workspace: Path) -> None:
        (workspace / "SOUL.md").write_text("soul content", encoding="utf-8")
        mm = MagicMock()
        mm.get_context.return_value = "some memory"

        with patch("hal.core.context.compiler.SkillsLoader") as cls:
            cls.return_value = MagicMock(
                get_always_skills=MagicMock(return_value=[]),
                build_skills_summary=MagicMock(return_value=""),
            )
            cc = ContextCompiler(workspace, memory_manager=mm)

        prompt = cc.build_system_prompt()
        # Identity, bootstrap, and memory layers should be separated by ---
        assert "\n\n---\n\n" in prompt


# ---------------------------------------------------------------------------
# build_messages()
# ---------------------------------------------------------------------------


class TestBuildMessages:
    def test_starts_with_system_message(self, compiler: ContextCompiler) -> None:
        msgs = compiler.build_messages([], "Hello")
        assert msgs[0]["role"] == "system"

    def test_ends_with_user_message(self, compiler: ContextCompiler) -> None:
        msgs = compiler.build_messages([], "Hello")
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == "Hello"

    def test_includes_history(self, compiler: ContextCompiler) -> None:
        history: list[dict[str, Any]] = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
        ]
        msgs = compiler.build_messages(history, "Follow-up")
        # system, history[0], history[1], current user
        assert len(msgs) == 4
        assert msgs[1]["content"] == "Hi"
        assert msgs[2]["content"] == "Hello!"
        assert msgs[3]["content"] == "Follow-up"

    def test_channel_and_chat_id_in_system_prompt(self, compiler: ContextCompiler) -> None:
        msgs = compiler.build_messages([], "msg", channel="telegram", chat_id="12345")
        system_content = msgs[0]["content"]
        assert "Channel: telegram" in system_content
        assert "Chat ID: 12345" in system_content

    def test_no_session_section_without_channel(self, compiler: ContextCompiler) -> None:
        msgs = compiler.build_messages([], "msg")
        system_content = msgs[0]["content"]
        assert "Current Session" not in system_content

    def test_no_session_section_with_only_channel(self, compiler: ContextCompiler) -> None:
        msgs = compiler.build_messages([], "msg", channel="telegram")
        system_content = msgs[0]["content"]
        # Both channel and chat_id are required
        assert "Current Session" not in system_content

    def test_media_none_returns_plain_text(self, compiler: ContextCompiler) -> None:
        msgs = compiler.build_messages([], "Hello", media=None)
        assert msgs[-1]["content"] == "Hello"

    def test_media_with_image(self, compiler: ContextCompiler, workspace: Path) -> None:
        # Create a tiny valid PNG (1x1 pixel)
        img_path = workspace / "test.png"
        # Minimal 1x1 PNG
        png_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
            "nGNgYPgPAAEDAQAIicLsAAAABJRU5ErkJggg=="
        )
        img_path.write_bytes(png_bytes)

        msgs = compiler.build_messages([], "Describe this", media=[str(img_path)])
        user_content = msgs[-1]["content"]
        assert isinstance(user_content, list)
        # Should contain image_url entry and text entry
        types = [item["type"] for item in user_content]
        assert "image_url" in types
        assert "text" in types

    def test_media_with_nonexistent_file(self, compiler: ContextCompiler) -> None:
        msgs = compiler.build_messages([], "Hello", media=["/no/such/file.png"])
        # Falls back to plain text when no valid images
        assert msgs[-1]["content"] == "Hello"

    def test_media_with_non_image_file(self, compiler: ContextCompiler, workspace: Path) -> None:
        txt = workspace / "data.txt"
        txt.write_text("not an image", encoding="utf-8")
        msgs = compiler.build_messages([], "Hello", media=[str(txt)])
        assert msgs[-1]["content"] == "Hello"


# ---------------------------------------------------------------------------
# Message helpers
# ---------------------------------------------------------------------------


class TestMessageHelpers:
    def test_add_tool_result(self, compiler: ContextCompiler) -> None:
        msgs: list[dict[str, Any]] = []
        result = compiler.add_tool_result(msgs, "call_1", "read_file", "file content")
        assert result is msgs
        assert len(msgs) == 1
        assert msgs[0] == {
            "role": "tool",
            "tool_call_id": "call_1",
            "name": "read_file",
            "content": "file content",
        }

    def test_add_assistant_message_text_only(self, compiler: ContextCompiler) -> None:
        msgs: list[dict[str, Any]] = []
        result = compiler.add_assistant_message(msgs, "Sure, here you go.")
        assert result is msgs
        assert msgs[0]["role"] == "assistant"
        assert msgs[0]["content"] == "Sure, here you go."
        assert "tool_calls" not in msgs[0]

    def test_add_assistant_message_with_tool_calls(self, compiler: ContextCompiler) -> None:
        msgs: list[dict[str, Any]] = []
        tool_calls = [{"id": "tc_1", "type": "function", "function": {"name": "ls"}}]
        compiler.add_assistant_message(msgs, None, tool_calls=tool_calls)
        assert msgs[0]["content"] == ""
        assert msgs[0]["tool_calls"] == tool_calls

    def test_add_assistant_message_none_content(self, compiler: ContextCompiler) -> None:
        msgs: list[dict[str, Any]] = []
        compiler.add_assistant_message(msgs, None)
        assert msgs[0]["content"] == ""
