from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

import hal.cli.commands as commands
from hal.infra.config.loader import save_config
from hal.infra.config.schema import Config

runner = CliRunner()


def test_version_flag_exits_0() -> None:
    result = runner.invoke(commands.app, ["--version"])
    assert result.exit_code == 0
    assert "hal v" in result.output


def _read_cron_store(home: Path) -> tuple[Path, dict]:
    store_path = home / ".hal" / "cron" / "jobs.json"
    assert store_path.exists()
    return store_path, json.loads(store_path.read_text(encoding="utf-8"))


def test_cron_add_list_run_enable_remove(tmp_home: Path) -> None:
    # Add job (every)
    add = runner.invoke(
        commands.app,
        [
            "cron",
            "add",
            "--name",
            "daily",
            "--message",
            "hello",
            "--every",
            "60",
        ],
    )
    assert add.exit_code == 0

    store_path, data = _read_cron_store(tmp_home)
    assert data.get("jobs"), f"Expected jobs in {store_path}"
    job_id = data["jobs"][0]["id"]

    # List jobs
    lst = runner.invoke(commands.app, ["cron", "list"])
    assert lst.exit_code == 0

    # Disable
    dis = runner.invoke(commands.app, ["cron", "enable", job_id, "--disable"])
    assert dis.exit_code == 0

    # Run job with --force even if disabled
    run = runner.invoke(commands.app, ["cron", "run", job_id, "--force"])
    assert run.exit_code == 0
    assert "Job executed" in run.output

    # Re-load store and ensure lastStatus updated
    _, data2 = _read_cron_store(tmp_home)
    state = data2["jobs"][0].get("state") or {}
    assert state.get("lastStatus") in {"ok", "error"}

    # Remove
    rm = runner.invoke(commands.app, ["cron", "remove", job_id])
    assert rm.exit_code == 0

    # Store should be empty
    _, data3 = _read_cron_store(tmp_home)
    assert data3.get("jobs") == []


def test_cron_add_requires_schedule(tmp_home: Path) -> None:
    result = runner.invoke(
        commands.app,
        [
            "cron",
            "add",
            "--name",
            "x",
            "--message",
            "hi",
        ],
    )
    assert result.exit_code != 0


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

    called = {}

    class Result:
        def __init__(self, stdout: str = "", stderr: str = ""):
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(cmd, env=None, check=None, capture_output=None, text=None):
        if cmd == ["node", "--help"]:
            return Result(stdout="  --use-env-proxy")
        called["cmd"] = cmd
        called["env"] = env
        called["check"] = check
        return Result()

    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/node")
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")

    result = runner.invoke(
        commands.app,
        ["anyrouter", "bridge", "--port", "4318", "--upstream", "https://anyrouter.top"],
    )
    assert result.exit_code == 0
    assert called["cmd"][0] == "node"
    assert "--use-env-proxy" in called["cmd"]
    assert called["check"] is True
    assert called["env"]["ANYROUTER_BRIDGE_PORT"] == "4318"
    assert called["env"]["ANYROUTER_INJECT_CLAUDE_CODE_SYSTEM"] == "true"
    assert called["env"]["ANYROUTER_VERBOSE"] == "true"
