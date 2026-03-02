"""CLI commands for HaL."""

import asyncio
from pathlib import Path

import typer
from rich.console import Console

from hal import __logo__, __version__
from hal.cli.factory import (
    make_memory_search,
    make_provider,
    make_summary_provider,
    make_worker_provider,
)

app = typer.Typer(
    name="hal",
    help=f"{__logo__} HaL - Digital Butler",
    no_args_is_help=True,
)
anyrouter_app = typer.Typer(help="Manage AnyRouter bridge")
app.add_typer(anyrouter_app, name="anyrouter")

console = Console()
ANYROUTER_DEFAULT_BETA = (
    "claude-code-20250219,oauth-2025-04-20,fine-grained-tool-streaming-2025-05-14,"
    "interleaved-thinking-2025-05-14"
)
ANYROUTER_DEFAULT_USER_AGENT = "claude-cli/2.1.2 (external, cli)"


_DEFAULT_MODEL_SENTINEL = "default"


def _resolve_worker_model(primary_model: str, worker_model: str) -> str:
    """Resolve worker model config where 'default' means using the primary model."""
    return primary_model if worker_model == _DEFAULT_MODEL_SENTINEL else worker_model


def version_callback(value: bool):
    if value:
        console.print(f"{__logo__} hal v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(None, "--version", "-v", callback=version_callback, is_eager=True),
):
    """HaL - Digital Butler."""
    pass


# ============================================================================
# AnyRouter
# ============================================================================


def _resolve_anyrouter_bridge_script() -> Path | None:
    """Find bundled AnyRouter bridge script."""
    candidate = Path(__file__).resolve().parent.parent / "bridge" / "anyrouter_bridge.mjs"
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


# ============================================================================
# Gateway / Server
# ============================================================================


@app.command()
def gateway(
    port: int = typer.Option(18790, "--port", "-p", help="Gateway port"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Start the HaL gateway."""
    from hal.bus.queue import MessageBus
    from hal.channels.manager import ChannelManager
    from hal.core.engine import AgentLoop
    from hal.infra.config.loader import load_config

    if verbose:
        import logging

        logging.basicConfig(level=logging.DEBUG)

    console.print(f"{__logo__} Starting HaL gateway on port {port}...")

    config = load_config()
    bus = MessageBus()
    provider = make_provider(config)

    memory_search = make_memory_search(config) if config.memory_search.enabled else None
    worker_provider = make_worker_provider(config) or provider
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        max_iterations=config.agents.defaults.max_tool_iterations,
        web_search_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        summary_model=config.agents.defaults.summary_model,
        summary_provider=make_summary_provider(config),
        worker_model=config.agents.defaults.worker_model,
        worker_provider=worker_provider,
        memory_search=memory_search,
        auto_inject_top_k=config.memory_search.auto_inject_top_k,
        recall_min_score=config.memory_search.recall_min_score,
        history_config=config.agents.defaults.history,
        engine_config=config.engine,
        web_search_config=config.tools.web.search,
        web_fetch_config=config.tools.web.fetch,
    )

    # Create channel manager
    channels = ChannelManager(
        config,
        bus,
        memory_manager=agent.memory,
        context_inspector=agent.inspect_context,
        outbound_poll_timeout_s=config.channels.outbound_poll_timeout_s,
    )

    if channels.enabled_channels:
        console.print(f"[green]✓[/green] Channels enabled: {', '.join(channels.enabled_channels)}")
    else:
        console.print("[yellow]Warning: No channels enabled[/yellow]")

    async def run():
        nonlocal memory_search
        try:
            # Initialize memory search if enabled
            if memory_search:
                try:
                    await memory_search.initialize()
                    backfill_count = await memory_search.backfill()
                    status = (
                        f"initialized ({backfill_count} chunks backfilled)"
                        if backfill_count
                        else "initialized"
                    )
                    console.print(f"[green]✓[/green] Memory search {status}")
                except Exception as e:
                    console.print(f"[yellow]Memory search init failed: {e}[/yellow]")
                    agent.disable_memory_search()
                    memory_search = None

            tasks = [
                agent.run(),
                channels.start_all(),
            ]

            # Schedule daily export at midnight
            if memory_search:

                async def daily_export():
                    import datetime as _dt

                    while True:
                        now = _dt.datetime.now()
                        next_midnight = now.replace(
                            hour=0, minute=0, second=0, microsecond=0
                        ) + _dt.timedelta(days=1)
                        wait_s = (next_midnight - now).total_seconds()
                        await asyncio.sleep(wait_s)
                        try:
                            count = await memory_search.export_and_index_yesterday()
                            if count:
                                from loguru import logger

                                logger.info(f"Daily export: indexed {count} chunks")
                        except Exception as e:
                            from loguru import logger

                            logger.warning(f"Daily export failed: {e}")

                tasks.append(daily_export())

            await asyncio.gather(*tasks)
        except KeyboardInterrupt:
            console.print("\nShutting down...")
            agent.stop()
            await channels.stop_all()

    asyncio.run(run())


if __name__ == "__main__":
    app()
