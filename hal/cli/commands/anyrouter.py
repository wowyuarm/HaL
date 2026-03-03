"""AnyRouter bridge command group."""

from __future__ import annotations

from pathlib import Path

import typer

from .root import anyrouter_app, console

ANYROUTER_DEFAULT_BETA = (
    "claude-code-20250219,oauth-2025-04-20,fine-grained-tool-streaming-2025-05-14,"
    "interleaved-thinking-2025-05-14"
)
ANYROUTER_DEFAULT_USER_AGENT = "claude-cli/2.1.2 (external, cli)"


def _resolve_anyrouter_bridge_script() -> Path | None:
    """Find bundled AnyRouter bridge script."""
    candidate = Path(__file__).resolve().parents[2] / "bridge" / "anyrouter_bridge.mjs"
    return candidate if candidate.exists() else None


def _node_supports_env_proxy() -> bool:
    """Check if Node supports --use-env-proxy."""
    import subprocess

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
    import os
    import shutil
    import subprocess

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

    resolved_upstream = upstream
    if not resolved_upstream:
        configured = cfg.api_base or ""
        resolved_upstream = configured if "anyrouter" in configured else "https://anyrouter.top"

    env = os.environ.copy()
    env.update(
        {
            "ANYROUTER_BRIDGE_HOST": host,
            "ANYROUTER_BRIDGE_PORT": str(port),
            "ANYROUTER_UPSTREAM": resolved_upstream,
            "ANYROUTER_API_KEY": resolved_key,
            "ANYROUTER_USER_AGENT": ANYROUTER_DEFAULT_USER_AGENT,
            "ANYROUTER_X_APP": "cli",
            "ANYROUTER_ANTHROPIC_BETA": ANYROUTER_DEFAULT_BETA,
            "ANYROUTER_DIRECT_BROWSER_ACCESS": "true",
            "ANYROUTER_FORCE_STREAM": "true" if force_stream else "false",
            "ANYROUTER_INJECT_CLAUDE_CODE_SYSTEM": "true" if inject_system else "false",
            "ANYROUTER_VERBOSE": "true" if verbose else "false",
        }
    )

    console.print(f"{__logo__} Starting AnyRouter bridge at http://{host}:{port}")
    console.print("Set providers.anyrouter.api_base to this local URL in ~/.hal/config.yaml")
    console.print(f"Upstream: {resolved_upstream}\n")

    proxy_vars = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")
    proxy_enabled = any(env.get(k) for k in proxy_vars)
    node_cmd = ["node"]
    if proxy_enabled:
        if _node_supports_env_proxy():
            node_cmd.append("--use-env-proxy")
            console.print("[dim]Proxy env detected, enabling Node --use-env-proxy[/dim]")
        else:
            console.print(
                "[yellow]Proxy env detected but this Node version does not support --use-env-proxy.[/yellow]"
            )

    try:
        subprocess.run([*node_cmd, str(script)], env=env, check=True)
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Bridge exited with error: {e}[/red]")
        raise typer.Exit(1) from e
    except KeyboardInterrupt:
        pass
