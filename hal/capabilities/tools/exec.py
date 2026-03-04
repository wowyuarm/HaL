"""Shell execution tool."""

import asyncio
import os
import re
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


class ExecTool(Tool):
    """Tool to execute shell commands."""

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
            r"\brm\s+-[rf]{1,2}\b",  # rm -r, rm -rf, rm -fr
            r"\bdel\s+/[fq]\b",  # del /f, del /q
            r"\brmdir\s+/s\b",  # rmdir /s
            r"(?:^|[;&|]\s*)format\b",  # format command (not URL params)
            r"\b(mkfs|diskpart)\b",  # other disk operations
            r"\bdd\s+if=",  # dd
            r">\s*/dev/sd",  # write to disk
            r"\b(shutdown|reboot|poweroff)\b",  # system power
            r":\(\)\s*\{.*\};\s*:",  # fork bomb
        ]
        self.allow_patterns = allow_patterns or []
        self.restrict_to_workspace = restrict_to_workspace

    @property
    def name(self) -> str:
        return "exec"

    @property
    def description(self) -> str:
        return "Execute a shell command and return its output. Use with caution."

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

        try:
            process = await self._create_process(command=command, cwd=cwd)
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
        stdout, stderr, timed_out = await self._read_process_output(process=process, timeout=timeout)
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
        """Extract command part of git commit, excluding -m/-F message content.

        Examples:
        - git commit -m "fix: kill process" -> returns "git commit"
        - git commit -F file.txt -> returns "git commit"
        """
        import shlex

        try:
            parts = shlex.split(cmd)
        except ValueError:
            # Malformed command, return as-is for safety
            return cmd

        result_parts = []
        skip_next = False

        for part in parts:
            if skip_next:
                skip_next = False
                continue

            # -m / --message / -f (lowered -F) / --file take the next token as value
            if part in ("-m", "--message", "-f", "--file"):
                skip_next = True
                continue

            # --message=content or --file=content
            if part.startswith(("--message=", "--file=")):
                continue

            # -m<content> (shlex merges -m"msg" into one token like -mmsg)
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
        return {"commands_run": [cmd[:200]]} if cmd else {}
