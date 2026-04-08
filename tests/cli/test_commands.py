from __future__ import annotations

import os
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


def test_workspace_doctor_command_reports_legacy_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "skills" / "demo").mkdir(parents=True)

    result = runner.invoke(commands.app, ["workspace", "doctor", "--workspace", str(workspace)])

    assert result.exit_code == 0
    assert "Legacy path can move to canonical location" in result.output
    assert "skills -> capabilities/skills" in result.output


def test_workspace_migrate_apply_moves_legacy_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "skills" / "demo").mkdir(parents=True)
    (workspace / "skills" / "demo" / "SKILL.md").write_text("demo", encoding="utf-8")

    result = runner.invoke(
        commands.app,
        ["workspace", "migrate", "--workspace", str(workspace), "--apply"],
    )

    assert result.exit_code == 0
    assert "APPLIED: skills -> capabilities/skills" in result.output
    assert (workspace / "capabilities" / "skills" / "demo" / "SKILL.md").read_text(
        encoding="utf-8"
    ) == "demo"


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
    assert called["env"]["ANYROUTER_REQUEST_TIMEOUT_MS"] == "45000"
    assert called["env"]["ANYROUTER_MAX_RETRIES"] == "2"
    assert called["env"]["ANYROUTER_RETRY_BASE_DELAY_MS"] == "750"
    assert called["env"]["ANYROUTER_STREAM_IDLE_TIMEOUT_MS"] == "30000"


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


def test_backend_origin_maps_wildcard_bind_host_to_loopback() -> None:
    assert web_command._backend_origin("0.0.0.0", 8765) == "http://127.0.0.1:8765"
    assert web_command._backend_origin("::", 8765) == "http://127.0.0.1:8765"
    assert web_command._backend_origin("localhost", 8765) == "http://localhost:8765"


def test_start_frontend_dev_server_passes_backend_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeProcess:
        def poll(self):
            return None

    def fake_popen(cmd, cwd=None, env=None):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env
        return FakeProcess()

    monkeypatch.setattr(web_command.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(web_command.subprocess, "Popen", fake_popen)

    process = web_command._start_frontend_dev_server(
        web_dir=Path("/tmp/web"),
        dev_host="0.0.0.0",
        dev_port=3000,
        backend_host="0.0.0.0",
        backend_port=8765,
    )

    assert process is not None
    assert captured["cmd"] == [
        "/usr/bin/npm",
        "run",
        "dev",
        "--",
        "--host",
        "0.0.0.0",
        "--port",
        "3000",
        "--strictPort",
    ]
    assert captured["cwd"] == Path("/tmp/web")
    assert captured["env"]["HAL_WEB_BACKEND_ORIGIN"] == "http://127.0.0.1:8765"


def test_web_command_starts_without_opening_browser(
    tmp_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = Config()
    config.web.host = "0.0.0.0"
    config.web.port = 4173

    server_state: dict[str, bool] = {"started": False, "stopped": False}

    class FakeAgent:
        async def run(self) -> None:
            return None

        def stop(self) -> None:
            return None

        def disable_recall_index(self) -> None:
            return None

    class FakeServer:
        def __init__(self, config_arg, bridge_arg) -> None:
            assert config_arg is config.web
            self.bridge = bridge_arg

        async def start(self) -> None:
            server_state["started"] = True

        async def stop(self) -> None:
            server_state["stopped"] = True

    monkeypatch.setattr(web_command, "_configure_logging", lambda *, verbose: None)
    monkeypatch.setattr("hal.infra.config.loader.load_config", lambda: config)
    monkeypatch.setattr(
        "hal.runtime.bootstrap.gateway.build_gateway_runtime",
        lambda cfg: SimpleNamespace(agent=FakeAgent(), recall_index=None),
    )
    monkeypatch.setattr(web_command, "_ensure_frontend_bundle_current", lambda: False)
    monkeypatch.setattr("hal.web.SessionBridge", lambda agent: ("bridge", agent))
    monkeypatch.setattr("hal.web.WebServer", FakeServer)

    result = runner.invoke(commands.app, ["web"])

    assert result.exit_code == 0
    assert server_state == {"started": True, "stopped": True}


def test_web_command_dev_mode_starts_vite(
    tmp_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = Config()
    config.web.host = "0.0.0.0"
    config.web.port = 4173

    server_state: dict[str, bool] = {"started": False, "stopped": False}
    dev_state: dict[str, object] = {"started": False, "stopped": False}

    class FakeAgent:
        async def run(self) -> None:
            return None

        def stop(self) -> None:
            return None

        def disable_recall_index(self) -> None:
            return None

    class FakeServer:
        def __init__(self, config_arg, bridge_arg) -> None:
            assert config_arg is config.web
            self.bridge = bridge_arg

        async def start(self) -> None:
            server_state["started"] = True

        async def stop(self) -> None:
            server_state["stopped"] = True

    monkeypatch.setattr(web_command, "_configure_logging", lambda *, verbose: None)
    monkeypatch.setattr("hal.infra.config.loader.load_config", lambda: config)
    monkeypatch.setattr(
        "hal.runtime.bootstrap.gateway.build_gateway_runtime",
        lambda cfg: SimpleNamespace(agent=FakeAgent(), recall_index=None),
    )
    monkeypatch.setattr(
        web_command,
        "_ensure_frontend_bundle_current",
        lambda: pytest.fail("static frontend rebuild should not run in --dev mode"),
    )
    monkeypatch.setattr("hal.web.SessionBridge", lambda agent: ("bridge", agent))
    monkeypatch.setattr("hal.web.WebServer", FakeServer)

    fake_process = object()
    monkeypatch.setattr(
        web_command,
        "_start_frontend_dev_server",
        lambda **kwargs: dev_state.update({"started": kwargs}) or fake_process,
    )
    monkeypatch.setattr(
        web_command,
        "_stop_frontend_dev_server",
        lambda process: dev_state.update({"stopped": process is fake_process}),
    )

    result = runner.invoke(commands.app, ["web", "--dev", "--dev-port", "3001"])

    assert result.exit_code == 0
    assert server_state == {"started": True, "stopped": True}
    assert dev_state["started"] == {
        "web_dir": web_command._FRONTEND_WORKSPACE_DIR,
        "dev_host": "0.0.0.0",
        "dev_port": 3001,
        "backend_host": "0.0.0.0",
        "backend_port": 4173,
    }
    assert dev_state["stopped"] is True


def test_frontend_bundle_needs_build_when_sources_are_newer(tmp_path: Path) -> None:
    web_dir = tmp_path / "web"
    src_dir = web_dir / "src"
    dist_dir = web_dir / "dist"
    src_dir.mkdir(parents=True)
    dist_dir.mkdir(parents=True)

    source_path = src_dir / "App.tsx"
    dist_path = dist_dir / "index.html"
    source_path.write_text("export default function App() { return null; }\n", encoding="utf-8")
    dist_path.write_text("<!doctype html>\n", encoding="utf-8")

    os.utime(dist_path, ns=(1_000_000_000, 1_000_000_000))
    os.utime(source_path, ns=(2_000_000_000, 2_000_000_000))

    assert web_command._frontend_bundle_needs_build(web_dir) is True


def test_frontend_bundle_needs_build_when_public_assets_are_newer(tmp_path: Path) -> None:
    web_dir = tmp_path / "web"
    public_dir = web_dir / "public"
    dist_dir = web_dir / "dist"
    public_dir.mkdir(parents=True)
    dist_dir.mkdir(parents=True)

    public_path = public_dir / "logo.svg"
    dist_path = dist_dir / "index.html"
    public_path.write_text("<svg />\n", encoding="utf-8")
    dist_path.write_text("<!doctype html>\n", encoding="utf-8")

    os.utime(dist_path, ns=(1_000_000_000, 1_000_000_000))
    os.utime(public_path, ns=(2_000_000_000, 2_000_000_000))

    assert web_command._frontend_bundle_needs_build(web_dir) is True


def test_frontend_bundle_ignores_newer_node_modules_files(tmp_path: Path) -> None:
    web_dir = tmp_path / "web"
    src_dir = web_dir / "src"
    dist_dir = web_dir / "dist"
    node_modules_dir = web_dir / "node_modules" / "vite"
    src_dir.mkdir(parents=True)
    dist_dir.mkdir(parents=True)
    node_modules_dir.mkdir(parents=True)

    source_path = src_dir / "App.tsx"
    dist_path = dist_dir / "index.html"
    dependency_path = node_modules_dir / "index.js"
    source_path.write_text("export default function App() { return null; }\n", encoding="utf-8")
    dist_path.write_text("<!doctype html>\n", encoding="utf-8")
    dependency_path.write_text("export {};\n", encoding="utf-8")

    os.utime(source_path, ns=(1_000_000_000, 1_000_000_000))
    os.utime(dist_path, ns=(2_000_000_000, 2_000_000_000))
    os.utime(dependency_path, ns=(3_000_000_000, 3_000_000_000))

    assert web_command._frontend_bundle_needs_build(web_dir) is False


def test_ensure_frontend_bundle_current_runs_npm_build_for_stale_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    web_dir = tmp_path / "web"
    src_dir = web_dir / "src"
    dist_dir = web_dir / "dist"
    src_dir.mkdir(parents=True)
    dist_dir.mkdir(parents=True)

    source_path = src_dir / "App.tsx"
    dist_path = dist_dir / "index.html"
    source_path.write_text("export default function App() { return null; }\n", encoding="utf-8")
    dist_path.write_text("<!doctype html>\n", encoding="utf-8")

    os.utime(dist_path, ns=(1_000_000_000, 1_000_000))
    os.utime(source_path, ns=(2_000_000_000, 2_000_000_000))

    called: dict[str, object] = {}

    monkeypatch.setattr(web_command.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(cmd, cwd=None, check=None):
        called["cmd"] = cmd
        called["cwd"] = cwd
        called["check"] = check
        return _FakeRunResult()

    monkeypatch.setattr(web_command.subprocess, "run", fake_run)

    rebuilt = web_command._ensure_frontend_bundle_current(web_dir)

    assert rebuilt is True
    assert called["cmd"] == ["/usr/bin/npm", "run", "build"]
    assert called["cwd"] == web_dir
    assert called["check"] is True


def test_thread_migrate_slug_command_rejects_missing_source(tmp_path: Path) -> None:
    result = runner.invoke(
        commands.app,
        ["thread", "migrate-slug", "nonexistent", "new-slug"],
    )
    assert result.exit_code == 1
    assert "does not exist" in result.output


def test_thread_migrate_slug_command_rejects_identical_slugs(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    (workspace / "work" / "threads" / "same-slug").mkdir(parents=True)

    result = runner.invoke(
        commands.app,
        ["thread", "migrate-slug", "--workspace", str(workspace), "same-slug", "same-slug"],
    )
    assert result.exit_code == 1
    assert "must differ" in result.output
