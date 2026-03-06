"""File system tools: read, write, edit."""

import difflib
from abc import abstractmethod
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from hal.capabilities.tools.base import Tool

# Maximum characters in fuzzy diagnostic output.
_DIAG_MAX_CHARS = 800
# Minimum similarity ratio to show a fuzzy match.
_DIAG_MIN_RATIO = 0.6
# Fuzzy diagnostics are best-effort; avoid scanning huge line windows.
_DIAG_MAX_WINDOWS = 5000
_FS_UNKNOWN_ACTION_ERROR = "Error: Unknown action '{action}'. Use one of: read, write, edit, list."
_FS_WRITE_MISSING_CONTENT_ERROR = "Error: 'content' parameter is required for write action."
_FS_EDIT_MISSING_PARAMS_ERROR = (
    "Error: 'old_text' and 'new_text' parameters are required for edit action."
)


def _resolve_path(path: str, allowed_dir: Path | None = None) -> Path:
    """Resolve path and optionally enforce directory restriction."""
    resolved = Path(path).expanduser().resolve()
    if allowed_dir:
        try:
            resolved.relative_to(allowed_dir.resolve())
        except ValueError:
            raise PermissionError(f"Path {path} is outside allowed directory {allowed_dir}")
    return resolved


def _resolve_existing_path(
    path: str, *, allowed_dir: Path | None = None, expect: str
) -> tuple[Path | None, str | None]:
    """Resolve a path and validate it exists with expected type."""
    try:
        resolved = _resolve_path(path, allowed_dir)
    except PermissionError as e:
        return None, f"Error: {e}"

    if expect == "file":
        if not resolved.exists():
            return None, f"Error: File not found: {path}"
        if not resolved.is_file():
            return None, f"Error: Not a file: {path}"
        return resolved, None

    if expect == "directory":
        if not resolved.exists():
            return None, f"Error: Directory not found: {path}"
        if not resolved.is_dir():
            return None, f"Error: Not a directory: {path}"
        return resolved, None

    raise ValueError(f"Unexpected path expectation: {expect!r}")


class _ExistingPathTool(Tool):
    """Base class for tools that require an existing file/directory path."""

    _EXPECTED_PATH_TYPE = "file"
    _ERROR_PREFIX = "Error: "

    def __init__(self, allowed_dir: Path | None = None):
        self._allowed_dir = allowed_dir

    async def execute(self, path: str, **kwargs: Any) -> str:
        try:
            resolved_path, error = _resolve_existing_path(
                path, allowed_dir=self._allowed_dir, expect=self._EXPECTED_PATH_TYPE
            )
            if error:
                return error
            assert resolved_path is not None
            return await self._execute_with_resolved_path(
                request_path=path, resolved_path=resolved_path, **kwargs
            )
        except Exception as e:
            return f"{self._ERROR_PREFIX}{str(e)}"

    @abstractmethod
    async def _execute_with_resolved_path(
        self, *, request_path: str, resolved_path: Path, **kwargs: Any
    ) -> str:
        """Run tool logic after path validation."""


class ReadFileTool(_ExistingPathTool):
    """Tool to read file contents with pagination and line numbers."""

    _EXPECTED_PATH_TYPE = "file"
    _ERROR_PREFIX = "Error reading file: "
    _MAX_LINE_BYTES = 50 * 1024  # 50KB per line

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
        return await super().execute(path=path, offset=offset, limit=limit, **kwargs)

    async def _execute_with_resolved_path(
        self,
        *,
        request_path: str,
        resolved_path: Path,
        offset: int = 1,
        limit: int = 2000,
        **kwargs: Any,
    ) -> str:
        content = resolved_path.read_text(encoding="utf-8")
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
                    f"Use exec tool: head -c 51200 {request_path}]"
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


def _fuzzy_diagnostic(content: str, old_text: str) -> str:
    """Find the closest match for *old_text* in *content* and return a diff.

    Slides a line-based window over *content* and uses character-level
    similarity to find the best match.  Returns a unified diff when the
    ratio exceeds the threshold, or an empty string otherwise.
    """
    target_lines = old_text.splitlines(keepends=True)
    content_lines = content.splitlines(keepends=True)
    window = len(target_lines)
    if window == 0 or len(content_lines) == 0:
        return ""
    candidate_windows = len(content_lines) - window + 1
    if candidate_windows > _DIAG_MAX_WINDOWS:
        return ""

    best_ratio = 0.0
    best_start = 0

    for start in range(max(1, candidate_windows)):
        candidate_text = "".join(content_lines[start : start + window])
        ratio = difflib.SequenceMatcher(None, old_text, candidate_text).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_start = start

    if best_ratio < _DIAG_MIN_RATIO:
        return ""

    best_lines = content_lines[best_start : best_start + window]
    diff = difflib.unified_diff(
        target_lines,
        best_lines,
        fromfile="old_text (provided)",
        tofile=f"file (line {best_start + 1})",
    )
    result = "".join(diff)

    if len(result) > _DIAG_MAX_CHARS:
        result = result[:_DIAG_MAX_CHARS] + "\n... (truncated)"

    return result


class EditFileTool(_ExistingPathTool):
    """Tool to edit a file by replacing text."""

    _EXPECTED_PATH_TYPE = "file"
    _ERROR_PREFIX = "Error editing file: "

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
        return await super().execute(path=path, old_text=old_text, new_text=new_text, **kwargs)

    async def _execute_with_resolved_path(
        self,
        *,
        request_path: str,
        resolved_path: Path,
        old_text: str,
        new_text: str,
        **kwargs: Any,
    ) -> str:
        content = resolved_path.read_text(encoding="utf-8")

        if old_text not in content:
            diag = _fuzzy_diagnostic(content, old_text)
            base = "Error: old_text not found in file."
            if diag:
                return f"{base}\n\nNearest match found:\n{diag}"
            return f"{base} Make sure it matches exactly."

        # Count occurrences
        count = content.count(old_text)
        if count > 1:
            return f"Warning: old_text appears {count} times. Please provide more context to make it unique."

        new_content = content.replace(old_text, new_text, 1)
        resolved_path.write_text(new_content, encoding="utf-8")

        return f"Successfully edited {request_path}"


class ListDirTool(_ExistingPathTool):
    """Tool to list directory contents."""

    _EXPECTED_PATH_TYPE = "directory"
    _ERROR_PREFIX = "Error listing directory: "

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

    async def _execute_with_resolved_path(
        self, *, request_path: str, resolved_path: Path, **kwargs: Any
    ) -> str:
        items = []
        for item in sorted(resolved_path.iterdir()):
            prefix = "📁 " if item.is_dir() else "📄 "
            items.append(f"{prefix}{item.name}")

        if not items:
            return f"Directory {request_path} is empty"

        return "\n".join(items)


_FsActionHandler = Callable[[str, dict[str, Any]], Awaitable[str]]


def _build_fs_action_handlers(allowed_dir: Path | None) -> dict[str, _FsActionHandler]:
    read_tool = ReadFileTool(allowed_dir=allowed_dir)
    write_tool = WriteFileTool(allowed_dir=allowed_dir)
    edit_tool = EditFileTool(allowed_dir=allowed_dir)
    list_tool = ListDirTool(allowed_dir=allowed_dir)

    async def run_read(path: str, kwargs: dict[str, Any]) -> str:
        offset = kwargs.get("offset", 1)
        limit = kwargs.get("limit", 2000)
        return await read_tool.execute(path=path, offset=offset, limit=limit)

    async def run_write(path: str, kwargs: dict[str, Any]) -> str:
        content = kwargs.get("content")
        if content is None:
            return _FS_WRITE_MISSING_CONTENT_ERROR
        return await write_tool.execute(path=path, content=content)

    async def run_edit(path: str, kwargs: dict[str, Any]) -> str:
        old_text = kwargs.get("old_text")
        new_text = kwargs.get("new_text")
        if old_text is None or new_text is None:
            return _FS_EDIT_MISSING_PARAMS_ERROR
        return await edit_tool.execute(path=path, old_text=old_text, new_text=new_text)

    async def run_list(path: str, kwargs: dict[str, Any]) -> str:
        return await list_tool.execute(path=path)

    return {
        "read": run_read,
        "write": run_write,
        "edit": run_edit,
        "list": run_list,
    }


class FsTool(Tool):
    """Unified file system tool that delegates to read/write/edit/list operations."""

    def __init__(self, allowed_dir: Path | None = None):
        self._handlers = _build_fs_action_handlers(allowed_dir)

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
        handler = self._handlers.get(action)
        if handler is None:
            return _FS_UNKNOWN_ACTION_ERROR.format(action=action)
        return await handler(path, kwargs)

    def get_side_effects(self, params: dict[str, Any]) -> dict[str, Any] | None:
        action = params.get("action", "")
        if action in ("write", "edit"):
            path = params.get("path", "")
            return {"files_modified": [path]} if path else {}
        return None
