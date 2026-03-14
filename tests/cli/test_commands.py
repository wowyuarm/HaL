from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import hal.cli.commands as commands
import hal.cli.commands.web as web_command
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


def test_browser_url_maps_wildcard_bind_host_to_loopback() -> None:
    assert web_command._browser_url("0.0.0.0", 8765) == "http://127.0.0.1:8765/"
    assert web_command._browser_url("::", 8765) == "http://127.0.0.1:8765/"
    assert web_command._browser_url("localhost", 8765) == "http://localhost:8765/"


def test_try_open_browser_uses_system_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []

    monkeypatch.setattr(web_command.webbrowser, "open_new_tab", lambda url: opened.append(url) or True)

    web_command._try_open_browser("localhost", 8765)

    assert opened == ["http://localhost:8765/"]


def test_web_command_opens_browser_after_server_start(
    tmp_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = Config()
    config.web.host = "0.0.0.0"
    config.web.port = 4173

    server_state: dict[str, bool] = {"started": False, "stopped": False}
    opened: list[tuple[str, int]] = []

    class FakeAgent:
        async def run(self) -> None:
            return None

        def stop(self) -> None:
            return None

        def disable_memory_search(self) -> None:
            return None

    class FakeServer:
        def __init__(self, config_arg, bridge_arg) -> None:
            assert config_arg is config.web
            self.bridge = bridge_arg

        async def start(self) -> None:
            server_state["started"] = True

        async def stop(self) -> None:
            server_state["stopped"] = True

    async def fake_to_thread(func, *args):
        func(*args)

    monkeypatch.setattr(web_command, "_configure_logging", lambda *, verbose: None)
    monkeypatch.setattr("hal.infra.config.loader.load_config", lambda: config)
    monkeypatch.setattr(
        "hal.runtime.bootstrap.gateway.build_gateway_runtime",
        lambda cfg: SimpleNamespace(agent=FakeAgent(), memory_search=None),
    )
    monkeypatch.setattr("hal.web.SessionBridge", lambda agent: ("bridge", agent))
    monkeypatch.setattr("hal.web.WebServer", FakeServer)
    monkeypatch.setattr(web_command.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(
        web_command,
        "_try_open_browser",
        lambda host, port: opened.append((host, port)),
    )

    result = runner.invoke(commands.app, ["web"])

    assert result.exit_code == 0
    assert server_state == {"started": True, "stopped": True}
    assert opened == [("0.0.0.0", 4173)]


def test_web_command_respects_no_open_flag(
    tmp_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = Config()
    opened = False

    class FakeAgent:
        async def run(self) -> None:
            return None

        def stop(self) -> None:
            return None

        def disable_memory_search(self) -> None:
            return None

    class FakeServer:
        def __init__(self, config_arg, bridge_arg) -> None:
            self.bridge = bridge_arg

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

    async def fake_to_thread(func, *args):
        nonlocal opened
        opened = True
        func(*args)

    monkeypatch.setattr(web_command, "_configure_logging", lambda *, verbose: None)
    monkeypatch.setattr("hal.infra.config.loader.load_config", lambda: config)
    monkeypatch.setattr(
        "hal.runtime.bootstrap.gateway.build_gateway_runtime",
        lambda cfg: SimpleNamespace(agent=FakeAgent(), memory_search=None),
    )
    monkeypatch.setattr("hal.web.SessionBridge", lambda agent: ("bridge", agent))
    monkeypatch.setattr("hal.web.WebServer", FakeServer)
    monkeypatch.setattr(web_command.asyncio, "to_thread", fake_to_thread)

    result = runner.invoke(commands.app, ["web", "--no-open"])

    assert result.exit_code == 0
    assert opened is False
