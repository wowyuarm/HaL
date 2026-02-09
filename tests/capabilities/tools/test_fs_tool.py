"""Tests for FsTool — the unified file system tool."""

import pytest

from hal.capabilities.tools.fs import FsTool


@pytest.fixture
def fs_tool(tmp_path):
    """Create an FsTool with allowed_dir set to tmp_path."""
    return FsTool(allowed_dir=tmp_path)


@pytest.fixture
def unrestricted_fs_tool():
    """Create an FsTool with no directory restriction."""
    return FsTool()


# ------------------------------------------------------------------
# Properties
# ------------------------------------------------------------------


class TestFsToolProperties:
    def test_name(self, fs_tool):
        assert fs_tool.name == "fs"

    def test_description_exists(self, fs_tool):
        assert isinstance(fs_tool.description, str)
        assert len(fs_tool.description) > 0

    def test_parameters_structure(self, fs_tool):
        params = fs_tool.parameters
        assert params["type"] == "object"
        props = params["properties"]
        assert "action" in props
        assert "path" in props
        assert "content" in props
        assert "old_text" in props
        assert "new_text" in props
        assert set(params["required"]) == {"action", "path"}
        assert props["action"]["enum"] == ["read", "write", "edit", "list"]


# ------------------------------------------------------------------
# Happy-path actions
# ------------------------------------------------------------------


class TestFsToolRead:
    async def test_read_file(self, unrestricted_fs_tool, tmp_path):
        target = tmp_path / "hello.txt"
        target.write_text("hello world", encoding="utf-8")

        result = await unrestricted_fs_tool.execute(action="read", path=str(target))
        assert result == "hello world"


class TestFsToolWrite:
    async def test_write_creates_file(self, unrestricted_fs_tool, tmp_path):
        target = tmp_path / "out.txt"
        result = await unrestricted_fs_tool.execute(
            action="write", path=str(target), content="new content"
        )

        assert "Successfully wrote" in result
        assert target.read_text(encoding="utf-8") == "new content"


class TestFsToolEdit:
    async def test_edit_replaces_text(self, unrestricted_fs_tool, tmp_path):
        target = tmp_path / "edit.txt"
        target.write_text("foo bar baz", encoding="utf-8")

        result = await unrestricted_fs_tool.execute(
            action="edit", path=str(target), old_text="bar", new_text="qux"
        )
        assert "Successfully edited" in result
        assert target.read_text(encoding="utf-8") == "foo qux baz"


class TestFsToolList:
    async def test_list_directory(self, unrestricted_fs_tool, tmp_path):
        (tmp_path / "a.txt").write_text("a", encoding="utf-8")
        (tmp_path / "subdir").mkdir()

        result = await unrestricted_fs_tool.execute(action="list", path=str(tmp_path))
        assert "a.txt" in result
        assert "subdir" in result


# ------------------------------------------------------------------
# Error paths
# ------------------------------------------------------------------


class TestFsToolErrors:
    async def test_unknown_action(self, unrestricted_fs_tool, tmp_path):
        result = await unrestricted_fs_tool.execute(action="delete", path=str(tmp_path))
        assert "Error" in result
        assert "Unknown action" in result

    async def test_read_nonexistent_file(self, unrestricted_fs_tool, tmp_path):
        result = await unrestricted_fs_tool.execute(action="read", path=str(tmp_path / "nope.txt"))
        assert "Error" in result
        assert "not found" in result.lower() or "File not found" in result

    async def test_write_without_content(self, unrestricted_fs_tool, tmp_path):
        result = await unrestricted_fs_tool.execute(action="write", path=str(tmp_path / "x.txt"))
        assert "Error" in result
        assert "content" in result.lower()

    async def test_edit_without_old_text(self, unrestricted_fs_tool, tmp_path):
        target = tmp_path / "e.txt"
        target.write_text("some text", encoding="utf-8")

        result = await unrestricted_fs_tool.execute(
            action="edit", path=str(target), new_text="replacement"
        )
        assert "Error" in result
        assert "old_text" in result

    async def test_edit_without_new_text(self, unrestricted_fs_tool, tmp_path):
        target = tmp_path / "e.txt"
        target.write_text("some text", encoding="utf-8")

        result = await unrestricted_fs_tool.execute(
            action="edit", path=str(target), old_text="some"
        )
        assert "Error" in result
        assert "new_text" in result


# ------------------------------------------------------------------
# allowed_dir restriction
# ------------------------------------------------------------------


class TestFsToolAllowedDir:
    async def test_read_blocked_outside_workspace(self, fs_tool, tmp_path):
        """Paths outside allowed_dir should be rejected."""
        result = await fs_tool.execute(action="read", path="/etc/passwd")
        assert "Error" in result
        assert "outside allowed directory" in result.lower() or "outside" in result.lower()

    async def test_write_blocked_outside_workspace(self, fs_tool, tmp_path):
        result = await fs_tool.execute(action="write", path="/tmp/evil.txt", content="bad")
        assert "Error" in result

    async def test_read_allowed_inside_workspace(self, fs_tool, tmp_path):
        """Paths inside allowed_dir should work normally."""
        target = tmp_path / "ok.txt"
        target.write_text("allowed", encoding="utf-8")

        result = await fs_tool.execute(action="read", path=str(target))
        assert result == "allowed"
