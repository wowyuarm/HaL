"""Shell execution tool with agent-friendly infrastructure."""

import asyncio
import os
import re
import shutil
from pathlib import Path
from typing import Any

from hal.capabilities.tools.base import Tool

_MAX_OUTPUT_CHARS = 10000
_ERR_MISSING_COMMAND = "Error: Missing required parameter 'command'"
_ERR_TIMEOUT = "Error: Command timed out after {seconds} seconds"
_ERR_BLOCKED_DANGEROUS = "Error: Command blocked by safety guard (dangerous pattern detected)"
_ERR_BLOCKED_ALLOWLIST = "Error: Command blocked by safety guard (not in allowlist)"
_ERR_BLOCKED_TRAVERSAL = "Error: Command blocked by safety guard (path traversal detected)"
_ERR_BLOCKED_OUTSIDE_CWD = "Error: Command blocked by safety guard (path outside working dir)"

# Commands where rtk adds significant value (verbose output).
_RTK_CANDIDATES = re.compile(
    r"^(?:git\s+(?:diff|log|show)|pytest|python\s+-m\s+pytest|ruff\s+check|ruff\s+format"
    r"|tsc|eslint|mypy|cargo\s+test|go\s+test)\b"
)

# Sensible defaults for agent-friendly search commands.
_RG_DEFAULTS: dict[str, str] = {
    "--color": "--color never",
    "--max-count": "--max-count 50",
}
_FD_DEFAULTS: dict[str, str] = {
    "--max-results": "--max-results 100",
}

# Resolved once at import time to avoid repeated $PATH searches.
_RTK_AVAILABLE: bool = shutil.which("rtk") is not None


def _inject_defaults(command: str, defaults: dict[str, str]) -> str:
    """Inject default flags into a command when not already present."""
    for flag, default_fragment in defaults.items():
        if flag not in command:
            # Insert after the command name (first whitespace boundary).
            parts = command.split(None, 1)
            if len(parts) == 2:
                command = f"{parts[0]} {default_fragment} {parts[1]}"
            else:
                command = f"{parts[0]} {default_fragment}"
    return command


def _prepare_command(command: str) -> tuple[str, str]:
    """Apply agent-friendly transformations to a command.

    Returns (actual_command, requested_command) where *requested_command* is
    the original input and *actual_command* is what will actually execute.
    """
    requested = command
    stripped = command.strip()

    # Inject sensible defaults for rg/fd.
    if re.match(r"^rg\b", stripped):
        command = _inject_defaults(stripped, _RG_DEFAULTS)
    elif re.match(r"^fd\b", stripped):
        command = _inject_defaults(stripped, _FD_DEFAULTS)

    # Transparent rtk proxy for known verbose commands.
    if _RTK_CANDIDATES.match(stripped) and _RTK_AVAILABLE:
        command = f"rtk {command}"

    return command, requested


class BashTool(Tool):
    """Agent-friendly shell execution with infrastructure commands."""

    def __init__(
        self,
        timeout: int = 60,
        kill_wait_s: int = 5,
        working_dir: str | None = None,
        deny_patterns: list[str] | None = None,
        allow_patterns: list[str] | None = None,
        restrict_to_workspace: bool = False,
    ):
        self.timeout = timeout
        self.kill_wait_s = kill_wait_s
        self.working_dir = working_dir
        self.deny_patterns = deny_patterns or [
            r"\brm\s+-[rf]{1,2}\b",
            r"\bdel\s+/[fq]\b",
            r"\brmdir\s+/s\b",
            r"(?:^|[;&|]\s*)format\b",
            r"\b(mkfs|diskpart)\b",
            r"\bdd\s+if=",
            r">\s*/dev/sd",
            r"\b(shutdown|reboot|poweroff)\b",
            r":\(\)\s*\{.*\};\s*:",
        ]
        self.allow_patterns = allow_patterns or []
        self.restrict_to_workspace = restrict_to_workspace

    @property
    def name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return "Execute shell commands in an equipped environment."

    @property
    def prompt(self) -> str:
        return (
            "Execute shell commands in an equipped environment.\n"
            "Available infrastructure: rg (content search), fd (file discovery), "
            "jq (JSON extraction), yq (YAML extraction), git, project build/test commands.\n"
            "Do NOT use bash for reading file contents (use read) or modifying files "
            "(use edit/write).\n"
            "Prefer rg over grep, fd over find, jq over awk-based JSON parsing. "
            "Keep output bounded — use result limits and avoid dumping large outputs.\n"
            "Output may be automatically optimized for token efficiency."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to execute"},
                "working_dir": {
                    "type": "string",
                    "description": "Optional working directory for the command",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Optional timeout in seconds (overrides default)",
                },
            },
            "required": ["command"],
        }

    async def execute(self, **kwargs: Any) -> str:
        command = kwargs.get("command")
        if not isinstance(command, str) or not command.strip():
            return _ERR_MISSING_COMMAND

        cwd = self._resolve_cwd(kwargs.get("working_dir"))
        guard_error = self._guard_command(command, cwd)
        if guard_error:
            return guard_error

        actual_timeout = self._resolve_timeout(kwargs.get("timeout"))

        # Apply agent-friendly transformations (rtk proxy, sensible defaults).
        actual_command, _requested = _prepare_command(command)

        try:
            process = await self._create_process(command=actual_command, cwd=cwd)
            return await self._collect_output(process=process, timeout=actual_timeout)
        except Exception as e:
            return f"Error executing command: {str(e)}"

    def _resolve_cwd(self, working_dir: Any) -> str:
        return working_dir or self.working_dir or os.getcwd()

    def _resolve_timeout(self, timeout: Any) -> Any:
        return timeout if timeout is not None else self.timeout

    async def _create_process(self, *, command: str, cwd: str) -> asyncio.subprocess.Process:
        return await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )

    async def _collect_output(self, *, process: asyncio.subprocess.Process, timeout: Any) -> str:
        stdout, stderr, timed_out = await self._read_process_output(
            process=process, timeout=timeout
        )
        if timed_out:
            return _ERR_TIMEOUT.format(seconds=timeout)
        return self._format_output(stdout=stdout, stderr=stderr, return_code=process.returncode)

    async def _read_process_output(
        self,
        *,
        process: asyncio.subprocess.Process,
        timeout: Any,
    ) -> tuple[bytes, bytes, bool]:
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            return stdout, stderr, False
        except asyncio.TimeoutError:
            process.kill()
            await self._wait_for_kill(process)
            return b"", b"", True

    async def _wait_for_kill(self, process: asyncio.subprocess.Process) -> None:
        try:
            await asyncio.wait_for(process.wait(), timeout=self.kill_wait_s)
        except asyncio.TimeoutError:
            pass

    def _format_output(self, *, stdout: bytes, stderr: bytes, return_code: int | None) -> str:
        output_parts: list[str] = []
        if stdout:
            output_parts.append(stdout.decode("utf-8", errors="replace"))

        if stderr:
            stderr_text = stderr.decode("utf-8", errors="replace")
            if stderr_text.strip():
                output_parts.append(f"STDERR:\n{stderr_text}")

        if return_code != 0:
            output_parts.append(f"\nExit code: {return_code}")

        result = "\n".join(output_parts) if output_parts else "(no output)"
        return self._truncate_output(result)

    def _truncate_output(self, result: str) -> str:
        if len(result) <= _MAX_OUTPUT_CHARS:
            return result
        extra = len(result) - _MAX_OUTPUT_CHARS
        return result[:_MAX_OUTPUT_CHARS] + f"\n... (truncated, {extra} more chars)"

    def _extract_git_commit_cmd_part(self, cmd: str) -> str:
        """Extract command part of git commit, excluding -m/-F message content."""
        import shlex

        try:
            parts = shlex.split(cmd)
        except ValueError:
            return cmd

        result_parts = []
        skip_next = False

        for part in parts:
            if skip_next:
                skip_next = False
                continue
            if part in ("-m", "--message", "-f", "--file"):
                skip_next = True
                continue
            if part.startswith(("--message=", "--file=")):
                continue
            if len(part) > 2 and part.startswith("-m"):
                continue
            result_parts.append(part)

        return " ".join(result_parts)

    def _guard_command(self, command: str, cwd: str) -> str | None:
        """Best-effort safety guard for potentially destructive commands."""
        cmd = command.strip()
        lower = cmd.lower()

        check_text = self._extract_guard_check_text(lower)
        if self._matches_any_pattern(check_text, self.deny_patterns):
            return _ERR_BLOCKED_DANGEROUS
        if self.allow_patterns and not self._matches_any_pattern(lower, self.allow_patterns):
            return _ERR_BLOCKED_ALLOWLIST
        if not self.restrict_to_workspace:
            return None
        return self._workspace_guard_error(cmd=cmd, cwd=cwd)

    def _extract_guard_check_text(self, lower_command: str) -> str:
        if not re.search(r"\bgit\s+commit\b", lower_command):
            return lower_command
        return self._extract_git_commit_cmd_part(lower_command)

    def _matches_any_pattern(self, text: str, patterns: list[str]) -> bool:
        return any(re.search(pattern, text) for pattern in patterns)

    def _workspace_guard_error(self, *, cmd: str, cwd: str) -> str | None:
        if "..\\" in cmd or "../" in cmd:
            return _ERR_BLOCKED_TRAVERSAL

        cwd_path = Path(cwd).resolve()
        for raw_path in self._extract_candidate_paths(cmd):
            if self._is_path_outside_cwd(raw_path=raw_path, cwd_path=cwd_path):
                return _ERR_BLOCKED_OUTSIDE_CWD
        return None

    def _extract_candidate_paths(self, command: str) -> list[str]:
        win_paths = re.findall(r"[A-Za-z]:\\[^\\\"']+", command)
        posix_paths = re.findall(r"/[^\s\"']+", command)
        return win_paths + posix_paths

    def _is_path_outside_cwd(self, *, raw_path: str, cwd_path: Path) -> bool:
        try:
            parsed = Path(raw_path).resolve()
        except Exception:
            return False
        return cwd_path not in parsed.parents and parsed != cwd_path

    def get_side_effects(self, params: dict[str, Any]) -> dict[str, Any] | None:
        cmd = params.get("command", "")
        if not cmd:
            return None
        actual, requested = _prepare_command(cmd)
        entry = actual[:200]
        if actual != requested:
            entry = f"{requested[:200]} -> {entry}"
        return {"commands_run": [entry]}
