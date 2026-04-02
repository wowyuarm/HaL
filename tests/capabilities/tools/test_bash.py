from __future__ import annotations

import asyncio

import pytest

from hal.capabilities.tools.bash import BashTool, _prepare_command


def test_guard_blocks_dangerous_patterns() -> None:
    tool = BashTool()
    err = tool._guard_command("rm -rf /", cwd="/")
    assert err and "blocked" in err.lower()


def test_guard_allowlist_blocks_when_not_matched() -> None:
    tool = BashTool(allow_patterns=[r"^echo\b"])
    err = tool._guard_command("ls", cwd="/")
    assert err and "allowlist" in err.lower()


def test_guard_allowlist_allows_when_matched() -> None:
    tool = BashTool(allow_patterns=[r"^echo\b"])
    assert tool._guard_command("echo hi", cwd="/") is None


def test_guard_restrict_to_workspace_blocks_traversal() -> None:
    tool = BashTool(restrict_to_workspace=True)
    err = tool._guard_command("cat ../secret.txt", cwd="/tmp")
    assert err and "traversal" in err.lower()


def test_guard_restrict_to_workspace_blocks_paths_outside_working_dir(tmp_path) -> None:
    tool = BashTool(restrict_to_workspace=True)
    err = tool._guard_command("cat /etc/passwd", cwd=str(tmp_path))
    assert err and "outside" in err.lower()


@pytest.mark.asyncio
async def test_execute_collects_stdout_stderr_and_exit_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    tool = BashTool(timeout=1, working_dir=str(tmp_path))

    class DummyProc:
        def __init__(self, stdout: bytes, stderr: bytes, returncode: int):
            self._stdout = stdout
            self._stderr = stderr
            self.returncode = returncode
            self.killed = False

        async def communicate(self):
            return self._stdout, self._stderr

        def kill(self) -> None:
            self.killed = True

    proc = DummyProc(b"OUT\n", b"ERR\n", returncode=2)

    async def fake_create(*args, **kwargs):
        return proc

    monkeypatch.setattr("hal.capabilities.tools.bash.asyncio.create_subprocess_shell", fake_create)

    out = await tool.execute(command="echo hi")

    assert "OUT" in out
    assert "STDERR" in out
    assert "Exit code: 2" in out


@pytest.mark.asyncio
async def test_execute_timeout_kills_process(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    tool = BashTool(timeout=1, working_dir=str(tmp_path))

    class DummyProc:
        returncode = None

        async def communicate(self):
            return b"", b""

        async def wait(self):
            return None

        def __init__(self):
            self.killed = False

        def kill(self) -> None:
            self.killed = True

    proc = DummyProc()

    async def fake_create(*args, **kwargs):
        return proc

    async def fake_wait_for(coro, timeout: float):
        # Close the coroutine to avoid "was never awaited" warnings in the timeout branch.
        coro.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr("hal.capabilities.tools.bash.asyncio.create_subprocess_shell", fake_create)
    monkeypatch.setattr("hal.capabilities.tools.bash.asyncio.wait_for", fake_wait_for)

    out = await tool.execute(command="echo hi")
    assert "timed out" in out.lower()
    assert proc.killed is True


@pytest.mark.asyncio
async def test_execute_truncates_long_output(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    tool = BashTool(timeout=1, working_dir=str(tmp_path))

    class DummyProc:
        def __init__(self):
            self.returncode = 0

        async def communicate(self):
            return b"a" * 11000, b""

        def kill(self) -> None:
            return None

    async def fake_create(*args, **kwargs):
        return DummyProc()

    monkeypatch.setattr("hal.capabilities.tools.bash.asyncio.create_subprocess_shell", fake_create)

    out = await tool.execute(command="echo hi")
    assert "truncated" in out.lower()


@pytest.mark.asyncio
async def test_execute_handles_subprocess_errors(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    tool = BashTool(timeout=1, working_dir=str(tmp_path))

    async def boom(*args, **kwargs):
        raise RuntimeError("nope")

    monkeypatch.setattr("hal.capabilities.tools.bash.asyncio.create_subprocess_shell", boom)

    out = await tool.execute(command="echo hi")
    assert "error executing command" in out.lower()


# --- New BashTool-specific tests ---


def test_prepare_command_injects_rg_defaults() -> None:
    actual, _requested = _prepare_command("rg pattern src/")
    assert "--color never" in actual
    assert "--max-count 50" in actual


def test_prepare_command_injects_fd_defaults() -> None:
    actual, _requested = _prepare_command("fd .py")
    assert "--max-results 100" in actual


def test_prepare_command_skips_existing_flags() -> None:
    actual, _requested = _prepare_command("rg --color auto pattern")
    assert "--color auto" in actual
    assert "--color never" not in actual


def test_tool_name_is_bash() -> None:
    assert BashTool().name == "bash"


def test_prompt_mentions_infrastructure() -> None:
    prompt = BashTool().prompt
    assert "rg" in prompt
    assert "fd" in prompt
    assert "jq" in prompt


def test_side_effects_records_transformed_command() -> None:
    tool = BashTool()
    effects = tool.get_side_effects({"command": "rg pattern"})
    assert effects is not None
    cmd = effects["commands_run"][0]
    # Side effects show requested -> actual when transformed.
    assert "rg pattern" in cmd
    assert "--color never" in cmd
    assert "--max-count 50" in cmd
    assert "->" in cmd
