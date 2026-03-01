"""Shell execution tool."""

import asyncio
import os
import re
from pathlib import Path
from typing import Any

from hal.capabilities.tools.base import Tool


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
            return "Error: Missing required parameter 'command'"

        working_dir = kwargs.get("working_dir")
        timeout = kwargs.get("timeout")
        cwd = working_dir or self.working_dir or os.getcwd()
        guard_error = self._guard_command(command, cwd)
        if guard_error:
            return guard_error

        # Use provided timeout or default
        actual_timeout = timeout if timeout is not None else self.timeout

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=actual_timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                try:
                    await asyncio.wait_for(process.wait(), timeout=self.kill_wait_s)
                except asyncio.TimeoutError:
                    pass  # Process didn't exit in time, but we tried
                return f"Error: Command timed out after {actual_timeout} seconds"

            output_parts = []

            if stdout:
                output_parts.append(stdout.decode("utf-8", errors="replace"))

            if stderr:
                stderr_text = stderr.decode("utf-8", errors="replace")
                if stderr_text.strip():
                    output_parts.append(f"STDERR:\n{stderr_text}")

            if process.returncode != 0:
                output_parts.append(f"\nExit code: {process.returncode}")

            result = "\n".join(output_parts) if output_parts else "(no output)"

            # Truncate very long output
            max_len = 10000
            if len(result) > max_len:
                result = result[:max_len] + f"\n... (truncated, {len(result) - max_len} more chars)"

            return result

        except Exception as e:
            return f"Error executing command: {str(e)}"

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

        # For git commit, extract the command part (exclude commit message content)
        check_text = lower
        if re.search(r"\bgit\s+commit\b", lower):
            check_text = self._extract_git_commit_cmd_part(lower)

        for pattern in self.deny_patterns:
            if re.search(pattern, check_text):
                return "Error: Command blocked by safety guard (dangerous pattern detected)"

        if self.allow_patterns:
            if not any(re.search(p, lower) for p in self.allow_patterns):
                return "Error: Command blocked by safety guard (not in allowlist)"

        if self.restrict_to_workspace:
            if "..\\" in cmd or "../" in cmd:
                return "Error: Command blocked by safety guard (path traversal detected)"

            cwd_path = Path(cwd).resolve()

            win_paths = re.findall(r"[A-Za-z]:\\[^\\\"']+", cmd)
            posix_paths = re.findall(r"/[^\s\"']+", cmd)

            for raw in win_paths + posix_paths:
                try:
                    p = Path(raw).resolve()
                except Exception:
                    continue
                if cwd_path not in p.parents and p != cwd_path:
                    return "Error: Command blocked by safety guard (path outside working dir)"

        return None

    def get_side_effects(self, params: dict[str, Any]) -> dict[str, Any] | None:
        cmd = params.get("command", "")
        return {"commands_run": [cmd[:200]]} if cmd else {}
