---
name: claude-collab
description: Collaborate with Claude Code CLI for deep code analysis, refactoring, and multi-step collaboration. Use this when users request working with Claude, need architecture review, or require iterative analysis of complex codebases.
requires_bins: ["claude"]
---


# Claude Collab

Execute Claude Code CLI in non-interactive (`-p`) mode for programmatic collaboration on coding tasks.

## Tool

`claude_exec.py` — subprocess wrapper around `claude -p --dangerously-skip-permissions`. Automatically tracks session state (first call creates, subsequent calls resume).

```bash
# Single query (no session persistence)
python scripts/claude_exec.py "Analyze the structure of src/main.py"

# Multi-turn session (pass any UUID — auto-creates on first, auto-resumes after)
python scripts/claude_exec.py --session <uuid> "Read src/main.py and suggest refactoring"
python scripts/claude_exec.py --session <uuid> "Apply the refactoring you suggested"

# JSON output (structured result)
python scripts/claude_exec.py --json "List all exported functions in lib/"

# Custom timeout (default 300s)
python scripts/claude_exec.py --timeout 600 "Refactor the entire module"
```

## Workflow: Multi-turn Task Collaboration

When the user asks you to collaborate with Claude Code on a task, follow this process:

### 1. Plan before delegating

Break the user's request into concrete, verifiable steps. Do not send a vague instruction like "refactor everything" — Claude Code works best with focused, specific prompts.

### 2. Use a session for multi-step tasks

Generate a UUID for the session ID and reuse it across calls. The script auto-detects whether to create or resume. Claude Code retains context — it can reference files it read earlier without re-reading.

### 3. One step at a time

Send one instruction per call. Wait for the result. Review it before sending the next instruction. This keeps you in control and avoids compounding errors.

### 4. Verify results yourself

After Claude Code reports completion, use your own tools (fs read, exec) to verify the output — check that files were actually modified, code compiles, tests pass. Do not blindly trust the response.

### 5. Iterate or stop

If the result is incomplete or wrong, send a follow-up in the same session with specific correction instructions. If satisfactory, summarize the outcome to the user.

## Notes

- Claude Code runs in the current working directory. Use `cd /path && python scripts/claude_exec.py ...` to target a specific project.
- Default timeout is 300s. Complex tasks (large refactors, multi-file changes) may need `--timeout 600`.
- The exec tool's own timeout (`tools.exec.timeout`) must be >= the timeout passed to `claude_exec.py`.
- `--dangerously-skip-permissions` is used automatically — Claude Code will execute file writes and shell commands without confirmation.
