"""AnyRouter bridge command group."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import typer

from .root import anyrouter_app, console

ANYROUTER_DEFAULT_BETA = (
    "claude-code-20250219,oauth-2025-04-20,fine-grained-tool-streaming-2025-05-14"
)
ANYROUTER_DEFAULT_USER_AGENT = "claude-cli/2.1.2 (external, cli)"
ANYROUTER_DEFAULT_X_APP = "cli"
ANYROUTER_DEFAULT_THINKING_EFFORT = "high"
ANYROUTER_DEFAULT_REQUEST_TIMEOUT_MS = 45_000
ANYROUTER_DEFAULT_MAX_RETRIES = 2
ANYROUTER_DEFAULT_RETRY_BASE_DELAY_MS = 750
ANYROUTER_DEFAULT_STREAM_IDLE_TIMEOUT_MS = 30_000
ANYROUTER_THINKING_EFFORTS = {"low", "medium", "high", "max"}
ANYROUTER_DEFAULT_UPSTREAM = "https://anyrouter.top"
ANYROUTER_PROXY_ENV_VARS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")


def _resolve_anyrouter_bridge_script() -> Path | None:
    """Find bundled AnyRouter bridge script."""
    candidate = Path(__file__).resolve().parents[2] / "bridge" / "anyrouter_bridge.mjs"
    return candidate if candidate.exists() else None


def _node_supports_env_proxy() -> bool:
    """Check if Node supports --use-env-proxy."""
    try:
        result = subprocess.run(
            ["node", "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    output = f"{result.stdout}\n{result.stderr}"
    return "--use-env-proxy" in output


def _resolve_header_value(
    extra_headers: dict[str, str] | None,
    name: str,
    default: str,
) -> str:
    """Read a header from config in a case-insensitive way with fallback."""
    if not extra_headers:
        return default
    target = name.lower()
    for key, value in extra_headers.items():
        if key.lower() != target:
            continue
        normalized = value.strip()
        if normalized:
            return normalized
    return default


def _resolve_default_thinking_effort(request_params: object) -> str:
    """Read adaptive effort from request_params.output_config.effort when configured."""
    if not isinstance(request_params, dict):
        return ANYROUTER_DEFAULT_THINKING_EFFORT
    output_config = request_params.get("output_config")
    if not isinstance(output_config, dict):
        return ANYROUTER_DEFAULT_THINKING_EFFORT
    effort = output_config.get("effort")
    if not isinstance(effort, str):
        return ANYROUTER_DEFAULT_THINKING_EFFORT
    normalized = effort.strip().lower()
    if normalized in ANYROUTER_THINKING_EFFORTS:
        return normalized
    return ANYROUTER_DEFAULT_THINKING_EFFORT


def _resolve_upstream(upstream_override: str, configured_api_base: str | None) -> str:
    """Resolve upstream URL from CLI override then config fallback."""
    if upstream_override:
        return upstream_override
    configured = configured_api_base or ""
    if "anyrouter" in configured:
        return configured
    return ANYROUTER_DEFAULT_UPSTREAM


def _build_bridge_env(
    *,
    host: str,
    port: int,
    upstream: str,
    api_key: str,
    user_agent: str,
    x_app: str,
    beta: str,
    thinking_effort: str,
    force_stream: bool,
    inject_system: bool,
    verbose: bool,
) -> dict[str, str]:
    """Build environment variables for the Node AnyRouter bridge."""
    env = os.environ.copy()
    env.update(
        {
            "ANYROUTER_BRIDGE_HOST": host,
            "ANYROUTER_BRIDGE_PORT": str(port),
            "ANYROUTER_UPSTREAM": upstream,
            "ANYROUTER_API_KEY": api_key,
            "ANYROUTER_USER_AGENT": user_agent,
            "ANYROUTER_X_APP": x_app,
            "ANYROUTER_ANTHROPIC_BETA": beta,
            "ANYROUTER_DIRECT_BROWSER_ACCESS": "true",
            "ANYROUTER_FORCE_STREAM": "true" if force_stream else "false",
            "ANYROUTER_INJECT_CLAUDE_CODE_SYSTEM": "true" if inject_system else "false",
            "ANYROUTER_DEFAULT_THINKING_EFFORT": thinking_effort,
            "ANYROUTER_VERBOSE": "true" if verbose else "false",
            "ANYROUTER_REQUEST_TIMEOUT_MS": str(ANYROUTER_DEFAULT_REQUEST_TIMEOUT_MS),
            "ANYROUTER_MAX_RETRIES": str(ANYROUTER_DEFAULT_MAX_RETRIES),
            "ANYROUTER_RETRY_BASE_DELAY_MS": str(ANYROUTER_DEFAULT_RETRY_BASE_DELAY_MS),
            "ANYROUTER_STREAM_IDLE_TIMEOUT_MS": str(ANYROUTER_DEFAULT_STREAM_IDLE_TIMEOUT_MS),
        }
    )
    return env


def _resolve_node_command(env: dict[str, str]) -> tuple[list[str], bool, bool]:
    """Build node command and report proxy detection/support flags."""
    proxy_enabled = any(env.get(key) for key in ANYROUTER_PROXY_ENV_VARS)
    node_supports_proxy_flag = proxy_enabled and _node_supports_env_proxy()

    node_cmd = ["node"]
    if node_supports_proxy_flag:
        node_cmd.append("--use-env-proxy")

    return node_cmd, proxy_enabled, node_supports_proxy_flag


def _run_bridge_process(node_cmd: list[str], script: Path, env: dict[str, str]) -> None:
    """Run bridge process and convert process failures to CLI exits."""
    try:
        subprocess.run([*node_cmd, str(script)], env=env, check=True)
    except subprocess.CalledProcessError as error:
        console.print(f"[red]Bridge exited with error: {error}[/red]")
        raise typer.Exit(1) from error
    except KeyboardInterrupt:
        return


@anyrouter_app.command("bridge")
def anyrouter_bridge(
    host: str = typer.Option("127.0.0.1", help="Bridge host"),
    port: int = typer.Option(3181, help="Bridge port"),
    upstream: str = typer.Option("", help="AnyRouter upstream URL"),
    api_key: str = typer.Option("", help="AnyRouter API key override"),
    force_stream: bool = typer.Option(True, "--force-stream/--no-force-stream"),
    inject_system: bool = typer.Option(True, "--inject-system/--no-inject-system"),
    verbose: bool = typer.Option(
        True,
        "--verbose/--quiet",
        help="Bridge logs detail level (default: verbose metadata, no message content)",
    ),
):
    """Start local Node bridge for AnyRouter (fixes Python TLS fingerprint mismatch)."""
    from hal import __logo__
    from hal.infra.config.loader import load_config

    if not shutil.which("node"):
        console.print("[red]node not found. Please install Node.js >= 18.[/red]")
        raise typer.Exit(1)

    script = _resolve_anyrouter_bridge_script()
    if not script:
        console.print("[red]AnyRouter bridge script not found in package.[/red]")
        raise typer.Exit(1)

    config = load_config()
    cfg = config.providers.anyrouter

    resolved_key = api_key or cfg.api_key
    if not resolved_key:
        console.print("[red]AnyRouter API key not configured.[/red]")
        console.print("Set providers.anyrouter.api_key in ~/.hal/auth.yaml or pass --api-key")
        raise typer.Exit(1)

    resolved_upstream = _resolve_upstream(upstream, cfg.api_base)

    resolved_user_agent = _resolve_header_value(
        cfg.extra_headers,
        "user-agent",
        ANYROUTER_DEFAULT_USER_AGENT,
    )
    resolved_x_app = _resolve_header_value(cfg.extra_headers, "x-app", ANYROUTER_DEFAULT_X_APP)
    resolved_beta = _resolve_header_value(
        cfg.extra_headers, "anthropic-beta", ANYROUTER_DEFAULT_BETA
    )
    resolved_thinking_effort = _resolve_default_thinking_effort(cfg.request_params)

    env = _build_bridge_env(
        host=host,
        port=port,
        upstream=resolved_upstream,
        api_key=resolved_key,
        user_agent=resolved_user_agent,
        x_app=resolved_x_app,
        beta=resolved_beta,
        thinking_effort=resolved_thinking_effort,
        force_stream=force_stream,
        inject_system=inject_system,
        verbose=verbose,
    )

    console.print(f"{__logo__} Starting AnyRouter bridge at http://{host}:{port}")
    console.print("Set providers.anyrouter.api_base to this local URL in ~/.hal/config.yaml")
    console.print(f"Upstream: {resolved_upstream}\n")

    node_cmd, proxy_enabled, proxy_flag_enabled = _resolve_node_command(env)
    if proxy_enabled and proxy_flag_enabled:
        console.print("[dim]Proxy env detected, enabling Node --use-env-proxy[/dim]")
    elif proxy_enabled:
        console.print(
            "[yellow]Proxy env detected but this Node version does not support --use-env-proxy.[/yellow]"
        )

    _run_bridge_process(node_cmd, script, env)
