"""File system tools: read, write, edit."""

from pathlib import Path
from typing import Any

from hal.capabilities.tools.base import Tool


def _resolve_path(path: str, allowed_dir: Path | None = None) -> Path:
    """Resolve path and optionally enforce directory restriction."""
    resolved = Path(path).expanduser().resolve()
    if allowed_dir and not str(resolved).startswith(str(allowed_dir.resolve())):
        raise PermissionError(f"Path {path} is outside allowed directory {allowed_dir}")
    return resolved


class ReadFileTool(Tool):
    """Tool to read file contents with pagination and line numbers."""

    _MAX_LINE_BYTES = 50 * 1024  # 50KB per line

    def __init__(self, allowed_dir: Path | None = None):
        self._allowed_dir = allowed_dir

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return (
            "Read the contents of a file with line numbers. "
            "Returns up to `limit` lines starting from `offset`. "
            "If the file has more lines, a hint is appended to continue reading."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path to read"},
                "offset": {
                    "type": "integer",
                    "description": "Line number to start reading from (1-based, default 1)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to return (default 2000)",
                },
            },
            "required": ["path"],
        }

    async def execute(self, path: str, offset: int = 1, limit: int = 2000, **kwargs: Any) -> str:
        try:
            file_path = _resolve_path(path, self._allowed_dir)
            if not file_path.exists():
                return f"Error: File not found: {path}"
            if not file_path.is_file():
                return f"Error: Not a file: {path}"

            content = file_path.read_text(encoding="utf-8")
            lines = content.split("\n")
            # Remove trailing empty line from final newline
            if lines and lines[-1] == "":
                lines.pop()
            total = len(lines)

            if total == 0:
                return "(empty file)"

            offset = max(1, offset)
            start_idx = offset - 1
            end_idx = min(start_idx + limit, total)

            output_lines = []
            for i in range(start_idx, end_idx):
                line = lines[i]
                lineno = i + 1
                if len(line.encode("utf-8", errors="replace")) > self._MAX_LINE_BYTES:
                    size_kb = len(line.encode("utf-8", errors="replace")) / 1024
                    output_lines.append(
                        f"[Line {lineno} is {size_kb:.1f}KB, exceeds 50.0KB limit. "
                        f"Use exec tool: head -c 51200 {path}]"
                    )
                else:
                    output_lines.append(f"{lineno:>6}\t{line}")

            result = "\n".join(output_lines)

            if end_idx < total:
                result += (
                    f"\n\n[Showing lines {offset}-{end_idx} of {total}. "
                    f"Use offset={end_idx + 1} to continue.]"
                )

            return result
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error reading file: {str(e)}"


class WriteFileTool(Tool):
    """Tool to write content to a file."""

    def __init__(self, allowed_dir: Path | None = None):
        self._allowed_dir = allowed_dir

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "Write content to a file at the given path. Creates parent directories if needed."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path to write to"},
                "content": {"type": "string", "description": "The content to write"},
            },
            "required": ["path", "content"],
        }

    async def execute(self, path: str, content: str, **kwargs: Any) -> str:
        try:
            file_path = _resolve_path(path, self._allowed_dir)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            return f"Successfully wrote {len(content)} bytes to {path}"
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error writing file: {str(e)}"


class EditFileTool(Tool):
    """Tool to edit a file by replacing text."""

    def __init__(self, allowed_dir: Path | None = None):
        self._allowed_dir = allowed_dir

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return "Edit a file by replacing old_text with new_text. The old_text must exist exactly in the file."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path to edit"},
                "old_text": {"type": "string", "description": "The exact text to find and replace"},
                "new_text": {"type": "string", "description": "The text to replace with"},
            },
            "required": ["path", "old_text", "new_text"],
        }

    async def execute(self, path: str, old_text: str, new_text: str, **kwargs: Any) -> str:
        try:
            file_path = _resolve_path(path, self._allowed_dir)
            if not file_path.exists():
                return f"Error: File not found: {path}"

            content = file_path.read_text(encoding="utf-8")

            if old_text not in content:
                return "Error: old_text not found in file. Make sure it matches exactly."

            # Count occurrences
            count = content.count(old_text)
            if count > 1:
                return f"Warning: old_text appears {count} times. Please provide more context to make it unique."

            new_content = content.replace(old_text, new_text, 1)
            file_path.write_text(new_content, encoding="utf-8")

            return f"Successfully edited {path}"
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error editing file: {str(e)}"


class ListDirTool(Tool):
    """Tool to list directory contents."""

    def __init__(self, allowed_dir: Path | None = None):
        self._allowed_dir = allowed_dir

    @property
    def name(self) -> str:
        return "list_dir"

    @property
    def description(self) -> str:
        return "List the contents of a directory."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "The directory path to list"}},
            "required": ["path"],
        }

    async def execute(self, path: str, **kwargs: Any) -> str:
        try:
            dir_path = _resolve_path(path, self._allowed_dir)
            if not dir_path.exists():
                return f"Error: Directory not found: {path}"
            if not dir_path.is_dir():
                return f"Error: Not a directory: {path}"

            items = []
            for item in sorted(dir_path.iterdir()):
                prefix = "📁 " if item.is_dir() else "📄 "
                items.append(f"{prefix}{item.name}")

            if not items:
                return f"Directory {path} is empty"

            return "\n".join(items)
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error listing directory: {str(e)}"


class FsTool(Tool):
    """Unified file system tool that delegates to read/write/edit/list operations."""

    def __init__(self, allowed_dir: Path | None = None):
        self._allowed_dir = allowed_dir
        self._read = ReadFileTool(allowed_dir=allowed_dir)
        self._write = WriteFileTool(allowed_dir=allowed_dir)
        self._edit = EditFileTool(allowed_dir=allowed_dir)
        self._list = ListDirTool(allowed_dir=allowed_dir)

    @property
    def name(self) -> str:
        return "fs"

    @property
    def description(self) -> str:
        return "File system operations: read, write, edit, or list files."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["read", "write", "edit", "list"],
                    "description": "The file operation to perform",
                },
                "path": {"type": "string", "description": "File or directory path"},
                "offset": {
                    "type": "integer",
                    "description": "Line to start reading from, 1-based (read action, default 1)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max lines to return (read action, default 2000)",
                },
                "content": {"type": "string", "description": "Content for write action"},
                "old_text": {"type": "string", "description": "Text to find (edit action)"},
                "new_text": {"type": "string", "description": "Replacement text (edit action)"},
            },
            "required": ["action", "path"],
        }

    async def execute(self, action: str, path: str, **kwargs: Any) -> str:
        if action == "read":
            offset = kwargs.get("offset", 1)
            limit = kwargs.get("limit", 2000)
            return await self._read.execute(path=path, offset=offset, limit=limit)
        elif action == "write":
            content = kwargs.get("content")
            if content is None:
                return "Error: 'content' parameter is required for write action."
            return await self._write.execute(path=path, content=content)
        elif action == "edit":
            old_text = kwargs.get("old_text")
            new_text = kwargs.get("new_text")
            if old_text is None or new_text is None:
                return "Error: 'old_text' and 'new_text' parameters are required for edit action."
            return await self._edit.execute(path=path, old_text=old_text, new_text=new_text)
        elif action == "list":
            return await self._list.execute(path=path)
        else:
            return f"Error: Unknown action '{action}'. Use one of: read, write, edit, list."
