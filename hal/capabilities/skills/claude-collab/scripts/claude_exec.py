#!/usr/bin/env python3
"""
Execute Claude Code CLI in non-interactive (--print) mode.

Supports single-shot queries and multi-turn conversations via --session.
On first call with a session ID, creates the session (--session-id).
On subsequent calls, resumes it (--resume).
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

# Track known sessions to auto-detect first vs resume
_SESSION_STORE = Path.home() / ".hal" / ".claude_sessions.json"


def _load_sessions() -> set[str]:
    if _SESSION_STORE.exists():
        return set(json.loads(_SESSION_STORE.read_text()))
    return set()


def _save_session(session_id: str) -> None:
    sessions = _load_sessions()
    sessions.add(session_id)
    _SESSION_STORE.parent.mkdir(parents=True, exist_ok=True)
    _SESSION_STORE.write_text(json.dumps(sorted(sessions)))


def build_command(question: str, session_id: str | None = None) -> list[str]:
    """Build the claude CLI command."""
    cmd = ["claude", "-p", "--dangerously-skip-permissions"]
    if session_id:
        known = _load_sessions()
        if session_id in known:
            cmd += ["--resume", session_id]
        else:
            cmd += ["--session-id", session_id]
    cmd.append(question)
    return cmd


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Claude Code in print mode")
    parser.add_argument("question", help="The question or instruction to send")
    parser.add_argument(
        "--session",
        default=None,
        help="Session ID (UUID) for multi-turn conversation",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Timeout in seconds (default: 300)",
    )
    parser.add_argument(
        "--json", action="store_true", help="Request JSON output format"
    )
    args = parser.parse_args()

    cmd = build_command(args.question, args.session)
    if args.json:
        cmd.insert(-1, "--output-format")
        cmd.insert(-1, "json")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=args.timeout,
        )
    except subprocess.TimeoutExpired:
        print(f"ERROR: Claude did not respond within {args.timeout}s", file=sys.stderr)
        sys.exit(1)

    if result.returncode == 0 and args.session:
        _save_session(args.session)

    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)

    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
