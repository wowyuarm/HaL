"""File system tools: read, write, edit."""

import difflib
from abc import abstractmethod
from pathlib import Path
from typing import Any

from hal.capabilities.tools.base import Tool

# Maximum characters in fuzzy diagnostic output.
_DIAG_MAX_CHARS = 800
# Minimum similarity ratio to show a fuzzy match.
_DIAG_MIN_RATIO = 0.6
# Fuzzy diagnostics are best-effort; avoid scanning huge line windows.
_DIAG_MAX_WINDOWS = 5000


def _resolve_path(
    path: str,
    allowed_dir: Path | None = None,
    base_dir: Path | None = None,
) -> Path:
    """Resolve path and optionally enforce directory restriction.

    Relative paths are resolved against *base_dir* when provided,
    otherwise against the process working directory.  Absolute paths
    and paths starting with ``~`` are unaffected by *base_dir*.
    """
    p = Path(path).expanduser()
    if base_dir and not p.is_absolute():
        p = base_dir / p
    resolved = p.resolve()
    if allowed_dir:
        try:
            resolved.relative_to(allowed_dir.resolve())
        except ValueError:
            raise PermissionError(f"Path {path} is outside allowed directory {allowed_dir}")
    return resolved


def _resolve_existing_path(
    path: str,
    *,
    allowed_dir: Path | None = None,
    base_dir: Path | None = None,
    expect: str,
) -> tuple[Path | None, str | None]:
    """Resolve a path and validate it exists with expected type."""
    try:
        resolved = _resolve_path(path, allowed_dir, base_dir)
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

    def __init__(self, allowed_dir: Path | None = None, base_dir: Path | None = None):
        self._allowed_dir = allowed_dir
        self._base_dir = base_dir

    async def execute(self, path: str, **kwargs: Any) -> str:
        try:
            resolved_path, error = _resolve_existing_path(
                path,
                allowed_dir=self._allowed_dir,
                base_dir=self._base_dir,
                expect=self._EXPECTED_PATH_TYPE,
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
        return "read"

    @property
    def description(self) -> str:
        return "Read file contents with line numbers and pagination."

    @property
    def prompt(self) -> str:
        return (
            "Read file contents with line numbers and pagination.\n"
            "Use when you need to inspect any file — code, config, briefs, notes, thread state.\n"
            "Do NOT use bash (cat/head/tail) for file reading. "
            "Use offset/limit for large files instead of reading everything.\n"
            "Output includes line numbers. A continuation hint appears when more lines exist."
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
                    f"Use bash: head -c 51200 {request_path}]"
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

    def __init__(self, allowed_dir: Path | None = None, base_dir: Path | None = None):
        self._allowed_dir = allowed_dir
        self._base_dir = base_dir

    @property
    def name(self) -> str:
        return "write"

    @property
    def description(self) -> str:
        return "Create or overwrite a file."

    @property
    def prompt(self) -> str:
        return (
            "Create or overwrite a file. Creates parent directories if needed.\n"
            "Use when producing new files or replacing entire file content.\n"
            "Prefer edit when modifying part of an existing file."
        )

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
            file_path = _resolve_path(path, self._allowed_dir, self._base_dir)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            return f"Successfully wrote {len(content)} bytes to {path}"
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error writing file: {str(e)}"

    def get_side_effects(self, params: dict[str, Any]) -> dict[str, Any] | None:
        path = params.get("path", "")
        return {"files_modified": [path]} if path else None


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
        return "edit"

    @property
    def description(self) -> str:
        return "Replace a specific text passage in an existing file."

    @property
    def prompt(self) -> str:
        return (
            "Replace a specific text passage in an existing file.\n"
            "Use for precise changes that preserve surrounding content.\n"
            "old_text must match exactly and uniquely. If match fails, re-read the file first.\n"
            "Do NOT use bash (sed/awk) for file editing.\n"
            "Always read the file first. For multiple changes, use a single edit with enough "
            "context to cover the full region rather than many small line-by-line edits."
        )

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

    def get_side_effects(self, params: dict[str, Any]) -> dict[str, Any] | None:
        path = params.get("path", "")
        return {"files_modified": [path]} if path else None
