"""Tests for individual file system tools: ReadFileTool, WriteFileTool, EditFileTool."""

import time

import pytest

from hal.capabilities.tools.fs import EditFileTool, ReadFileTool, WriteFileTool

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def read_tool():
    return ReadFileTool()


@pytest.fixture
def read_tool_restricted(tmp_path):
    return ReadFileTool(allowed_dir=tmp_path)


@pytest.fixture
def write_tool():
    return WriteFileTool()


@pytest.fixture
def write_tool_restricted(tmp_path):
    return WriteFileTool(allowed_dir=tmp_path)


@pytest.fixture
def edit_tool():
    return EditFileTool()


@pytest.fixture
def edit_tool_restricted(tmp_path):
    return EditFileTool(allowed_dir=tmp_path)


# ------------------------------------------------------------------
# Schema
# ------------------------------------------------------------------


class TestToSchema:
    def test_to_schema_uses_prompt_as_description(self):
        tool = ReadFileTool()
        schema = tool.to_schema()
        assert "Do NOT use bash" in schema["function"]["description"]
        assert len(schema["function"]["description"]) > len(tool.description)


# ------------------------------------------------------------------
# Side effects
# ------------------------------------------------------------------


class TestSideEffects:
    def test_edit_tool_reports_files_modified(self):
        tool = EditFileTool()
        effects = tool.get_side_effects({"path": "foo.py", "old_text": "a", "new_text": "b"})
        assert effects == {"files_modified": ["foo.py"]}

    def test_edit_tool_returns_none_without_path(self):
        tool = EditFileTool()
        assert tool.get_side_effects({"old_text": "a", "new_text": "b"}) is None

    def test_write_tool_reports_files_modified(self):
        tool = WriteFileTool()
        effects = tool.get_side_effects({"path": "bar.txt", "content": "hello"})
        assert effects == {"files_modified": ["bar.txt"]}

    def test_write_tool_returns_none_without_path(self):
        tool = WriteFileTool()
        assert tool.get_side_effects({"content": "hello"}) is None


# ------------------------------------------------------------------
# ReadFileTool
# ------------------------------------------------------------------


class TestReadFileTool:
    async def test_read_small_file_with_line_numbers(self, read_tool, tmp_path):
        target = tmp_path / "hello.txt"
        target.write_text("hello\nworld", encoding="utf-8")

        result = await read_tool.execute(path=str(target))
        assert "1\thello" in result
        assert "2\tworld" in result
        assert "Use offset=" not in result

    async def test_read_large_file_pagination(self, read_tool, tmp_path):
        target = tmp_path / "big.txt"
        lines = [f"line {i}" for i in range(1, 3001)]
        target.write_text("\n".join(lines), encoding="utf-8")

        result = await read_tool.execute(path=str(target))
        assert "1\tline 1" in result
        assert "2000\tline 2000" in result
        assert "line 2001" not in result
        assert "[Showing lines 1-2000 of 3000. Use offset=2001 to continue.]" in result

    async def test_read_with_offset(self, read_tool, tmp_path):
        target = tmp_path / "big.txt"
        lines = [f"line {i}" for i in range(1, 3001)]
        target.write_text("\n".join(lines), encoding="utf-8")

        result = await read_tool.execute(path=str(target), offset=2001)
        assert "2001\tline 2001" in result
        assert "3000\tline 3000" in result
        assert "Use offset=" not in result

    async def test_read_with_custom_limit(self, read_tool, tmp_path):
        target = tmp_path / "medium.txt"
        lines = [f"line {i}" for i in range(1, 101)]
        target.write_text("\n".join(lines), encoding="utf-8")

        result = await read_tool.execute(path=str(target), limit=10)
        assert "1\tline 1" in result
        assert "10\tline 10" in result
        assert "line 11" not in result
        assert "[Showing lines 1-10 of 100. Use offset=11 to continue.]" in result

    async def test_read_oversized_line(self, read_tool, tmp_path):
        target = tmp_path / "huge_line.txt"
        huge = "x" * (60 * 1024)
        target.write_text(huge, encoding="utf-8")

        result = await read_tool.execute(path=str(target))
        assert "exceeds 50.0KB limit" in result
        assert "Use bash" in result
        assert huge not in result

    async def test_read_empty_file(self, read_tool, tmp_path):
        target = tmp_path / "empty.txt"
        target.write_text("", encoding="utf-8")

        result = await read_tool.execute(path=str(target))
        assert result == "(empty file)"

    async def test_read_nonexistent_file(self, read_tool, tmp_path):
        result = await read_tool.execute(path=str(tmp_path / "nope.txt"))
        assert "Error" in result
        assert "not found" in result.lower() or "File not found" in result


# ------------------------------------------------------------------
# WriteFileTool
# ------------------------------------------------------------------


class TestWriteFileTool:
    async def test_write_creates_file(self, write_tool, tmp_path):
        target = tmp_path / "out.txt"
        result = await write_tool.execute(path=str(target), content="new content")

        assert "Successfully wrote" in result
        assert target.read_text(encoding="utf-8") == "new content"


# ------------------------------------------------------------------
# EditFileTool
# ------------------------------------------------------------------


class TestEditFileTool:
    async def test_edit_replaces_text(self, edit_tool, tmp_path):
        target = tmp_path / "edit.txt"
        target.write_text("foo bar baz", encoding="utf-8")

        result = await edit_tool.execute(path=str(target), old_text="bar", new_text="qux")
        assert "Successfully edited" in result
        assert target.read_text(encoding="utf-8") == "foo qux baz"


# ------------------------------------------------------------------
# Allowed-dir restriction
# ------------------------------------------------------------------


class TestAllowedDir:
    async def test_read_blocked_outside_workspace(self, read_tool_restricted):
        result = await read_tool_restricted.execute(path="/etc/passwd")
        assert "Error" in result
        assert "outside" in result.lower()

    async def test_write_blocked_outside_workspace(self, write_tool_restricted):
        result = await write_tool_restricted.execute(path="/tmp/evil.txt", content="bad")
        assert "Error" in result

    async def test_read_allowed_inside_workspace(self, read_tool_restricted, tmp_path):
        target = tmp_path / "ok.txt"
        target.write_text("allowed", encoding="utf-8")

        result = await read_tool_restricted.execute(path=str(target))
        assert "allowed" in result

    async def test_sibling_path_blocked(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        evil = tmp_path / "workspace-evil"
        evil.mkdir()
        (evil / "secret.txt").write_text("stolen", encoding="utf-8")

        tool = ReadFileTool(allowed_dir=workspace)
        result = await tool.execute(path=str(evil / "secret.txt"))
        assert "Error" in result

    async def test_parent_traversal_blocked(self, read_tool_restricted, tmp_path):
        result = await read_tool_restricted.execute(
            path=str(tmp_path / "subdir" / ".." / ".." / "etc" / "passwd")
        )
        assert "Error" in result


# ------------------------------------------------------------------
# Edit fuzzy match diagnostics
# ------------------------------------------------------------------


class TestEditFuzzyDiagnostics:
    async def test_typo_returns_fuzzy_diff(self, edit_tool, tmp_path):
        target = tmp_path / "fuzzy.txt"
        target.write_text("def hello_world():\n    return 42\n", encoding="utf-8")

        result = await edit_tool.execute(
            path=str(target),
            old_text="def hello_wrold():\n    return 42\n",
            new_text="def hello_world():\n    return 0\n",
        )
        assert "old_text not found" in result
        assert "Nearest match found:" in result
        assert "hello_world" in result

    async def test_unrelated_content_returns_generic_error(self, edit_tool, tmp_path):
        target = tmp_path / "unrelated.txt"
        target.write_text("alpha beta gamma\n", encoding="utf-8")

        result = await edit_tool.execute(
            path=str(target),
            old_text="xxxxxxxxx yyyyyy zzzzzzz\n",
            new_text="replacement\n",
        )
        assert "old_text not found" in result
        assert "Make sure it matches exactly" in result
        assert "Nearest match" not in result

    async def test_exact_match_still_works(self, edit_tool, tmp_path):
        target = tmp_path / "exact.txt"
        target.write_text("line one\nline two\n", encoding="utf-8")

        result = await edit_tool.execute(
            path=str(target),
            old_text="line one\n",
            new_text="line ONE\n",
        )
        assert "Successfully edited" in result
        assert target.read_text(encoding="utf-8") == "line ONE\nline two\n"

    async def test_large_file_completes_quickly(self, edit_tool, tmp_path):
        target = tmp_path / "large.txt"
        target.write_text("line\n" * 200_000, encoding="utf-8")

        start = time.monotonic()
        result = await edit_tool.execute(
            path=str(target),
            old_text="def nonexistent_function():\n    pass\n",
            new_text="replaced\n",
        )
        elapsed = time.monotonic() - start

        assert "old_text not found" in result
        assert elapsed < 5.0, f"Fuzzy diagnostic took {elapsed:.1f}s on ~1MB file"
