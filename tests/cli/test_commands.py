from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

import hal.cli.commands as commands
from hal.infra.config.loader import save_config
from hal.infra.config.schema import Config

runner = CliRunner()


class _FakeRunResult:
    def __init__(self, stdout: str = "", stderr: str = ""):
        self.stdout = stdout
        self.stderr = stderr


def _invoke_anyrouter_bridge(
    monkeypatch: pytest.MonkeyPatch,
    *,
    args: list[str],
    node_help_stdout: str,
    https_proxy: str | None = None,
) -> tuple[object, dict]:
    called: dict = {}

    def fake_run(cmd, env=None, check=None, capture_output=None, text=None):
        if cmd == ["node", "--help"]:
            return _FakeRunResult(stdout=node_help_stdout)
        called["cmd"] = cmd
        called["env"] = env
        called["check"] = check
        return _FakeRunResult()

    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/node")
    monkeypatch.setattr(subprocess, "run", fake_run)
    if https_proxy:
        monkeypatch.setenv("HTTPS_PROXY", https_proxy)

    result = runner.invoke(commands.app, args)
    return result, called


def test_version_flag_exits_0() -> None:
    result = runner.invoke(commands.app, ["--version"])
    assert result.exit_code == 0
    assert "hal v" in result.output


def test_resolve_worker_model_uses_primary_when_default() -> None:
    assert commands._resolve_worker_model("claude-opus", "default") == "claude-opus"


def test_resolve_worker_model_uses_worker_override() -> None:
    assert commands._resolve_worker_model("claude-opus", "gpt-5.3-codex") == "gpt-5.3-codex"


def test_anyrouter_bridge_requires_api_key(tmp_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/node")

    result = runner.invoke(commands.app, ["anyrouter", "bridge"])
    assert result.exit_code == 1
    assert "api key not configured" in result.output.lower()


def test_anyrouter_bridge_invokes_node_process(
    tmp_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = Config()
    cfg.providers.anyrouter.api_key = "sk-test"
    save_config(cfg)

    result, called = _invoke_anyrouter_bridge(
        monkeypatch,
        args=["anyrouter", "bridge", "--port", "4318", "--upstream", "https://anyrouter.top"],
        node_help_stdout="  --use-env-proxy",
        https_proxy="http://127.0.0.1:7890",
    )
    assert result.exit_code == 0
    assert called["cmd"][0] == "node"
    assert "--use-env-proxy" in called["cmd"]
    assert called["check"] is True
    assert called["env"]["ANYROUTER_BRIDGE_PORT"] == "4318"
    assert called["env"]["ANYROUTER_INJECT_CLAUDE_CODE_SYSTEM"] == "true"
    assert (
        called["env"]["ANYROUTER_ANTHROPIC_BETA"]
        == "claude-code-20250219,oauth-2025-04-20,fine-grained-tool-streaming-2025-05-14"
    )
    assert called["env"]["ANYROUTER_DEFAULT_THINKING_EFFORT"] == "high"
    assert called["env"]["ANYROUTER_VERBOSE"] == "true"


def test_anyrouter_bridge_uses_configured_header_and_effort_overrides(
    tmp_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = Config()
    cfg.providers.anyrouter.api_key = "sk-test"
    cfg.providers.anyrouter.extra_headers = {
        "User-Agent": "custom-cli/9.9.9",
        "X-App": "custom-app",
        "Anthropic-Beta": "claude-code-20250219",
    }
    cfg.providers.anyrouter.request_params = {"output_config": {"effort": "max"}}
    save_config(cfg)

    result, called = _invoke_anyrouter_bridge(
        monkeypatch,
        args=["anyrouter", "bridge", "--port", "4318"],
        node_help_stdout="",
    )
    assert result.exit_code == 0
    assert called["env"]["ANYROUTER_USER_AGENT"] == "custom-cli/9.9.9"
    assert called["env"]["ANYROUTER_X_APP"] == "custom-app"
    assert called["env"]["ANYROUTER_ANTHROPIC_BETA"] == "claude-code-20250219"
    assert called["env"]["ANYROUTER_DEFAULT_THINKING_EFFORT"] == "max"
