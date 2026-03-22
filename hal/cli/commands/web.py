"""``hal web`` command — start the native session-first web runtime."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import webbrowser
from pathlib import Path

import typer
from loguru import logger

from .gateway import _configure_logging
from .root import app, console

_BROWSER_LOCAL_HOSTS = {"0.0.0.0", "::"}
_FRONTEND_WORKSPACE_DIR = Path(__file__).resolve().parents[3] / "web"
_FRONTEND_DIST_DIRNAME = "dist"
_FRONTEND_IGNORED_DIRNAMES = {
    _FRONTEND_DIST_DIRNAME,
    "node_modules",
    ".git",
}
_FRONTEND_BUILD_COMMAND = ("npm", "run", "build")
_FRONTEND_DEV_COMMAND = ("npm", "run", "dev", "--")
_FRONTEND_DEV_DEFAULT_PORT = 3000
_FRONTEND_DEV_STARTUP_MESSAGE = "Starting Vite dev server..."


def _browser_url(host: str, port: int) -> str:
    """Translate bind host/port into a browser-friendly local URL."""
    browser_host = "127.0.0.1" if host in _BROWSER_LOCAL_HOSTS else host
    return f"http://{browser_host}:{port}/"


def _try_open_browser(host: str, port: int) -> None:
    """Best-effort browser launch after the web server is listening."""
    url = _browser_url(host, port)
    try:
        opened = webbrowser.open_new_tab(url)
    except Exception as exc:  # pragma: no cover - platform-specific browser failures
        logger.warning("failed to open browser for {}: {}", url, exc)
        console.print(f"[yellow]Could not open browser automatically.[/yellow] Visit {url}")
        return

    if not opened:
        console.print(f"[yellow]Browser did not open automatically.[/yellow] Visit {url}")


def _backend_origin(host: str, port: int) -> str:
    """Translate backend bind host/port into a frontend-friendly origin."""
    browser_host = "127.0.0.1" if host in _BROWSER_LOCAL_HOSTS else host
    return f"http://{browser_host}:{port}"


def _iter_frontend_source_files(web_dir: Path) -> list[Path]:
    source_files: list[Path] = []
    for root, dirnames, filenames in os.walk(web_dir, topdown=True):
        dirnames[:] = [dirname for dirname in dirnames if dirname not in _FRONTEND_IGNORED_DIRNAMES]
        root_path = Path(root)
        source_files.extend(root_path / filename for filename in filenames)
    return source_files


def _iter_frontend_dist_files(web_dir: Path) -> list[Path]:
    dist_dir = web_dir / _FRONTEND_DIST_DIRNAME
    if not dist_dir.is_dir():
        return []
    return [path for path in dist_dir.rglob("*") if path.is_file()]


def _latest_mtime_ns(paths: list[Path]) -> int:
    if not paths:
        return 0
    return max(path.stat().st_mtime_ns for path in paths)


def _frontend_bundle_needs_build(web_dir: Path) -> bool:
    dist_files = _iter_frontend_dist_files(web_dir)
    if not dist_files:
        return True
    source_files = _iter_frontend_source_files(web_dir)
    if not source_files:
        return False
    return _latest_mtime_ns(source_files) > _latest_mtime_ns(dist_files)


def _build_frontend_bundle(web_dir: Path) -> None:
    npm = shutil.which(_FRONTEND_BUILD_COMMAND[0])
    if npm is None:
        raise RuntimeError(
            "Frontend bundle is missing or stale, but `npm` is not available. "
            "Install Node.js and run `npm run build` in ./web."
        )

    console.print("[cyan]Frontend sources changed; rebuilding web bundle...[/cyan]")
    try:
        subprocess.run([npm, *_FRONTEND_BUILD_COMMAND[1:]], cwd=web_dir, check=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            "Frontend rebuild failed. Run `npm run build` in ./web to inspect the error."
        ) from exc


def _ensure_frontend_bundle_current(web_dir: Path | None = None) -> bool:
    resolved_web_dir = web_dir or _FRONTEND_WORKSPACE_DIR
    if not resolved_web_dir.is_dir():
        return False
    if not _frontend_bundle_needs_build(resolved_web_dir):
        return False
    _build_frontend_bundle(resolved_web_dir)
    return True


def _start_frontend_dev_server(
    *,
    web_dir: Path,
    dev_host: str,
    dev_port: int,
    backend_host: str,
    backend_port: int,
) -> subprocess.Popen[bytes]:
    npm = shutil.which(_FRONTEND_DEV_COMMAND[0])
    if npm is None:
        raise RuntimeError(
            "Frontend dev server requires `npm`. Install Node.js and run `npm install` in ./web."
        )

    env = os.environ.copy()
    env["HAL_WEB_BACKEND_ORIGIN"] = _backend_origin(backend_host, backend_port)
    command = [
        npm,
        *_FRONTEND_DEV_COMMAND[1:],
        "--host",
        dev_host,
        "--port",
        str(dev_port),
        "--strictPort",
    ]

    console.print(f"[cyan]{_FRONTEND_DEV_STARTUP_MESSAGE}[/cyan]")
    try:
        return subprocess.Popen(command, cwd=web_dir, env=env)
    except OSError as exc:
        raise RuntimeError(f"Frontend dev server failed to start: {exc}") from exc


def _stop_frontend_dev_server(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


@app.command()
def web(
    host: str | None = typer.Option(None, "--host", help="Web server bind host"),
    port: int | None = typer.Option(None, "--port", "-p", help="Web server bind port"),
    dev: bool = typer.Option(
        False,
        "--dev",
        help="Run the frontend with Vite dev server instead of serving ./web/dist",
    ),
    dev_port: int = typer.Option(
        _FRONTEND_DEV_DEFAULT_PORT,
        "--dev-port",
        help="Vite dev server port used with --dev",
    ),
    open_browser: bool = typer.Option(
        True,
        "--open/--no-open",
        help="Open the HaL web UI in a local browser after startup",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
) -> None:
    """Start HaL with the native web server and no IM channels."""
    from hal import __logo__
    from hal.infra.config.loader import load_config
    from hal.runtime.bootstrap.gateway import build_gateway_runtime
    from hal.web import SessionBridge, WebServer

    _configure_logging(verbose=verbose)

    config = load_config()
    config.channels.telegram.enabled = False
    if host is not None:
        config.web.host = host
    if port is not None:
        config.web.port = port

    effective_host = config.web.host
    effective_port = config.web.port
    frontend_host = effective_host
    frontend_port = dev_port if dev else effective_port

    frontend_rebuilt = False
    if not dev:
        try:
            frontend_rebuilt = _ensure_frontend_bundle_current()
        except RuntimeError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1) from exc
        if frontend_rebuilt:
            console.print("[green]\u2713[/green] Frontend rebuilt")

    if dev:
        console.print(
            f"{__logo__} Starting HaL web backend on {effective_host}:{effective_port} "
            f"with Vite dev frontend on {frontend_host}:{frontend_port}..."
        )
    else:
        console.print(
            f"{__logo__} Starting HaL native web runtime on {effective_host}:{effective_port}..."
        )

    runtime = build_gateway_runtime(config)
    agent = runtime.agent
    recall_index = runtime.recall_index
    server = WebServer(config.web, SessionBridge(agent))
    frontend_dev_process: subprocess.Popen[bytes] | None = None

    async def run() -> None:
        nonlocal frontend_dev_process, recall_index
        try:
            if recall_index:
                try:
                    await recall_index.initialize()
                    backfill_count = await recall_index.backfill()
                    status = (
                        f"initialized ({backfill_count} chunks backfilled)"
                        if backfill_count
                        else "initialized"
                    )
                    console.print(f"[green]\u2713[/green] Recall index {status}")
                except Exception as exc:
                    console.print(f"[yellow]Recall index init failed: {exc}[/yellow]")
                    agent.disable_recall_index()
                    recall_index = None

            await server.start()
            if dev:
                try:
                    frontend_dev_process = _start_frontend_dev_server(
                        web_dir=_FRONTEND_WORKSPACE_DIR,
                        dev_host=frontend_host,
                        dev_port=frontend_port,
                        backend_host=effective_host,
                        backend_port=effective_port,
                    )
                except RuntimeError as exc:
                    console.print(f"[red]{exc}[/red]")
                    raise typer.Exit(code=1) from exc
            if open_browser:
                await asyncio.to_thread(_try_open_browser, frontend_host, frontend_port)
            await agent.run()
        except KeyboardInterrupt:
            console.print("\nShutting down...")
        finally:
            _stop_frontend_dev_server(frontend_dev_process)
            agent.stop()
            await server.stop()

    asyncio.run(run())
