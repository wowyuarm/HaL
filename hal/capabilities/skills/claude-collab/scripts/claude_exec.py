#!/usr/bin/env python3
"""
Execute Claude Code CLI in non-interactive (--print) mode.

Supports single-shot queries and multi-turn conversations via --session/--resume.
Provides sensible safety defaults while exposing key CLI capabilities.

With --output FILE, results are written to a JSON task file instead of stdout,
enabling file-based async task delegation patterns.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time


def atomic_write_json(path: str, data: dict) -> None:
    """Write JSON to path atomically via tmp file + rename."""
    dir_name = os.path.dirname(os.path.abspath(path))
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp_path, path)
    except BaseException:
        # Clean up tmp file on any failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def is_third_party_configured() -> bool:
    """Check if third-party model is configured via environment variables."""
    return bool(
        os.environ.get("ANTHROPIC_BASE_URL") or os.environ.get("ANTHROPIC_API_KEY")
    )


def build_command(args: argparse.Namespace) -> list[str]:
    """Build the claude CLI command from parsed arguments."""
    cmd = ["claude", "-p"]

    # Session management: explicit create vs resume
    if args.resume:
        cmd += ["--resume", args.resume]
    elif args.session:
        cmd += ["--session-id", args.session]

    if args.continue_session:
        cmd.append("--continue")

    # Permission control (mutually exclusive group handled by argparse)
    if args.dangerously_skip_permissions:
        cmd.append("--dangerously-skip-permissions")
    elif args.permission_mode:
        cmd += ["--permission-mode", args.permission_mode]

    # --allowedTools and --disallowedTools are variadic (<tools...>) in the
    # Claude CLI, meaning they greedily consume all subsequent non-flag args.
    # Passing tools as separate args would cause the prompt (the last positional
    # arg) to be swallowed.  Pass the comma-separated string as a single value
    # instead — the CLI explicitly accepts "Comma or space-separated" input.
    if args.allowed_tools:
        cmd += ["--allowedTools", args.allowed_tools]

    if args.disallowed_tools:
        cmd += ["--disallowedTools", args.disallowed_tools]

    # Model selection (skip if third-party model is configured via env vars)
    if args.model and not is_third_party_configured():
        cmd += ["--model", args.model]

    # Execution limits
    if args.max_turns:
        cmd += ["--max-turns", str(args.max_turns)]
    if args.max_budget:
        cmd += ["--max-budget-usd", str(args.max_budget)]

    # Output format
    if args.output_format:
        cmd += ["--output-format", args.output_format]

    # System prompt injection
    if args.append_system_prompt:
        cmd += ["--append-system-prompt", args.append_system_prompt]

    # --add-dir is variadic (<directories...>); split and pass individually.
    # The prompt is protected by the -- separator below.
    if args.add_dir:
        for d in args.add_dir.split(","):
            cmd += ["--add-dir", d.strip()]

    # MCP configuration
    if args.mcp_config:
        cmd += ["--mcp-config", args.mcp_config]

    # Use -- to end option parsing, ensuring the prompt is never consumed
    # by variadic options like --allowedTools, --disallowedTools, or --add-dir.
    cmd.append("--")
    cmd.append(args.prompt)
    return cmd


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Claude Code in non-interactive print mode",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  # Single analysis query (read-only, safe)
  %(prog)s "Analyze the architecture of src/"

  # Start a new multi-turn session
  %(prog)s --session <uuid> "Read src/main.py and suggest improvements"

  # Resume an existing session
  %(prog)s --resume <uuid> "Apply the changes you suggested"

  # Read-only analysis with JSON output
  %(prog)s --permission-mode plan --output-format json "List all API endpoints"

  # Editing with explicit tool allowlist
  %(prog)s --allowed-tools "Read,Edit(src/**),Bash(npm test)" "Explain the auth module and fix the token bug"

  # Use a specific model with budget limit
  %(prog)s --model sonnet --max-budget 2.0 "Refactor the database layer"
""",
    )

    parser.add_argument(
        "prompt",
        nargs="?",
        default=None,
        help="The prompt to send to Claude Code (omit if using --plan-file)",
    )

    # Session management
    session_group = parser.add_mutually_exclusive_group()
    session_group.add_argument(
        "--session",
        metavar="UUID",
        help="Create a new session with this UUID",
    )
    session_group.add_argument(
        "--resume",
        metavar="ID",
        help="Resume an existing session by ID or name",
    )
    session_group.add_argument(
        "--continue-session",
        action="store_true",
        help="Continue the most recent session in the working directory",
    )

    # Permission control
    perm_group = parser.add_mutually_exclusive_group()
    perm_group.add_argument(
        "--permission-mode",
        choices=["default", "plan", "acceptEdits", "dontAsk", "bypassPermissions"],
        help="Set permission mode (default: relies on Claude Code defaults)",
    )
    perm_group.add_argument(
        "--dangerously-skip-permissions",
        action="store_true",
        help="Skip ALL permission checks (use only in isolated environments)",
    )
    parser.add_argument(
        "--allowed-tools",
        metavar="RULES",
        help='Comma-separated tool allow rules, e.g. "Read,Edit(src/**),Bash(npm test)"',
    )
    parser.add_argument(
        "--disallowed-tools",
        metavar="RULES",
        help='Comma-separated tool deny rules, e.g. "Bash,Write"',
    )

    # Model selection
    parser.add_argument(
        "--model",
        help="Model alias (sonnet, opus, haiku) or full model ID",
    )

    # Execution limits
    parser.add_argument(
        "--max-turns",
        type=int,
        help="Max agentic turns before stopping",
    )
    parser.add_argument(
        "--max-budget",
        type=float,
        help="Max budget in USD before stopping",
    )

    # Output
    parser.add_argument(
        "--output-format",
        choices=["text", "json", "stream-json"],
        help="Output format (default: text)",
    )

    # System prompt
    parser.add_argument(
        "--append-system-prompt",
        metavar="TEXT",
        help="Append additional instructions to Claude Code's system prompt",
    )

    # Working directory / MCP
    parser.add_argument(
        "--add-dir",
        metavar="PATHS",
        help='Comma-separated additional directories, e.g. "../other-project,/shared/libs"',
    )
    parser.add_argument(
        "--mcp-config",
        metavar="PATH",
        help="Path to MCP server configuration JSON file",
    )

    # Process control
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Subprocess timeout in seconds (default: 600)",
    )

    # Task file output
    parser.add_argument(
        "--output",
        metavar="FILE",
        help="Write results to a JSON task file instead of stdout",
    )

    # Plan file input
    parser.add_argument(
        "--plan-file",
        metavar="PATH",
        help="Read execution plan from file instead of command line argument",
    )

    args = parser.parse_args()

    # Resolve prompt from --plan-file if provided
    if args.plan_file:
        try:
            with open(args.plan_file) as f:
                args.prompt = f.read()
        except FileNotFoundError:
            print(
                f"ERROR: Plan file not found: {args.plan_file}",
                file=sys.stderr,
            )
            sys.exit(1)
        except OSError as e:
            print(
                f"ERROR: Cannot read plan file: {e}",
                file=sys.stderr,
            )
            sys.exit(1)

    if not args.prompt:
        parser.error("prompt is required (provide as argument or via --plan-file)")

    cmd = build_command(args)

    if args.output:
        _run_with_output_file(cmd, args)
    else:
        _run_direct(cmd, args)


def _run_direct(cmd: list[str], args: argparse.Namespace) -> None:
    """Original behavior: run Claude Code and pipe stdout/stderr directly."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=args.timeout,
        )
    except subprocess.TimeoutExpired:
        print(
            f"ERROR: Claude Code did not respond within {args.timeout}s. "
            "Consider increasing --timeout for complex tasks.",
            file=sys.stderr,
        )
        sys.exit(124)
    except FileNotFoundError:
        print(
            "ERROR: 'claude' command not found. "
            "Install Claude Code CLI: npm install -g @anthropic-ai/claude-code",
            file=sys.stderr,
        )
        sys.exit(127)

    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)

    sys.exit(result.returncode)


def _run_with_output_file(cmd: list[str], args: argparse.Namespace) -> None:
    """Write results to a JSON task file. stdout only emits the file path."""
    output_path = os.path.abspath(args.output)
    session_id = args.resume or args.session or None

    # Phase 1: write "running" status immediately
    running_status = {
        "status": "running",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "pid": os.getpid(),
    }
    if session_id:
        running_status["session_id"] = session_id
    atomic_write_json(output_path, running_status)

    # Phase 2: execute Claude Code synchronously
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=args.timeout,
        )
    except subprocess.TimeoutExpired:
        atomic_write_json(output_path, {
            "status": "timeout",
            "error": f"Claude Code did not respond within {args.timeout}s",
            "exit_code": 124,
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        print(output_path)
        sys.exit(124)
    except FileNotFoundError:
        atomic_write_json(output_path, {
            "status": "error",
            "error": "'claude' command not found",
            "exit_code": 127,
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        print(output_path)
        sys.exit(127)

    # Phase 3: write final result
    status = "completed" if result.returncode == 0 else "error"
    final = {
        "status": status,
        "output": result.stdout,
        "exit_code": result.returncode,
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if result.stderr:
        final["error"] = result.stderr
    if session_id:
        final["session_id"] = session_id
    atomic_write_json(output_path, final)

    print(output_path)


if __name__ == "__main__":
    main()
