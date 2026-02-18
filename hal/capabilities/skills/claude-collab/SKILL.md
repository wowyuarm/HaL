---
name: claude-collab
description: "Delegate coding execution to Claude Code CLI. Load this skill AFTER you have understood the user's intent (via OpenContext or conversation), researched the codebase (via subagents), and prepared a detailed execution plan. This skill teaches HOW to delegate execution — not what to build. Triggers: need to edit code, run commands, scaffold, refactor, or implement across a codebase."
---


# Claude Collab — Execution Delegation Protocol

## Mental Model

**You are the architect. Claude Code is the builder.**

You hold the full picture — project context (from OpenContext briefs), research results (from subagents), and user intent. Claude Code has **zero context**. Each invocation starts blank: your execution plan is its entire world.

**When to load this skill:** You already have a plan. You need someone to execute it.

**When NOT to load this skill:** You're still exploring, researching, or clarifying intent. Do that first — use OpenContext for project knowledge, subagents for research, and conversation for clarifying with the user.


## Your Place in the Workflow

```
User expresses intent
  → You load the project brief (OpenContext)
  → You clarify with the user if needed
  → You dispatch subagents for research (architecture, patterns, etc.)
  → You synthesize a detailed execution plan
  ─── YOU ARE HERE ───
  → You delegate execution to Claude Code (this skill)
  → Claude Code executes autonomously and returns results
  → You review (or delegate review to a subagent)
  → You report back to the user
```


## Execution Plan Template

Every delegation to Claude Code must be a **self-contained execution plan**. Claude Code cannot ask you questions — anticipate ambiguity.

```markdown
## Task
<one-line summary of what to accomplish>

## Background
<why this task exists — the problem encountered, user request, or need being addressed.
 This gives Claude Code the "why" behind the "what".>

## Working Directory
<absolute path to project root>

## Context
<only the facts Claude Code needs to execute — relevant file paths,
 architecture decisions, naming conventions, constraints.
 NOT your entire project brief — extract only what's relevant.>

## Steps
1. <concrete action with file paths and function names>
2. <concrete action>
...

## Acceptance Criteria
- [ ] <verifiable condition — can be checked by reading code or running a command>
- [ ] <verifiable condition>

## Constraints
- <things NOT to do>
- <style/pattern requirements from the project>
```

### Good Plans vs. Bad Plans

**Bad** (vague, assumes shared context):
- "Fix the login bug"
- "Refactor the database layer"
- "Apply the changes we discussed"

**Good** (self-contained, anchored, scoped):

```markdown
## Task
Fix premature token expiry in the auth module

## Background
Users report being logged out after 5 minutes. Investigation shows the refresh token TTL
is hardcoded to 300s instead of reading from config. This was introduced in commit abc123.

## Working Directory
/home/user/projects/my-api

## Context
- Express + TypeScript app
- Auth module: src/auth/token.ts — the `refresh()` method at line 42
- Token TTL is hardcoded to 300s but should read from config at src/config/auth.ts
- Project uses src/utils/logger.ts for logging (not console.log)

## Steps
1. In src/auth/token.ts, update `refresh()` to read TTL from src/config/auth.ts
2. Add `tokenTTL` field to the config schema in src/config/auth.ts (default: 3600)
3. Add test in tests/auth/token.test.ts covering the TTL configuration
4. Run `npm test` to verify all tests pass

## Acceptance Criteria
- [ ] TTL is configurable via src/config/auth.ts, not hardcoded
- [ ] Default TTL is 3600 seconds
- [ ] New test covers the configurable TTL path
- [ ] `npm test` exits with 0 failures

## Constraints
- Do not modify any files outside src/auth/ and src/config/
- Follow existing TypeScript strict mode conventions
- Use the project logger, not console.log
```


## Invocation

Claude Code runs with **full permissions by default** — we trust the model's judgment.

> **⚠️ Safety note:** `--dangerously-skip-permissions` grants Claude Code unrestricted file editing and command execution. This is appropriate when you trust the model and the environment. For restricted environments, see the Advanced section.

### Short tasks (stdout)

```bash
cd /path/to/project && python3 scripts/claude_exec.py \
  --dangerously-skip-permissions \
  "your execution plan here"
```

### Long tasks (file-based output)

```bash
cd /path/to/project && python3 scripts/claude_exec.py \
  --dangerously-skip-permissions \
  --output /tmp/task-result.json \
  "your execution plan here"
```

### Long plans (from file)

When the execution plan is large, write it to a file first to avoid shell argument limits:

```bash
cd /path/to/project && python3 scripts/claude_exec.py \
  --dangerously-skip-permissions \
  --output /tmp/task-result.json \
  --plan-file /tmp/execution-plan.md
```

### Multi-step sessions

Use sessions when Claude Code should retain context between steps:

```bash
SESSION_ID=$(python3 -c "import uuid; print(uuid.uuid4())")

# Step 1
cd /path/to/project && python3 scripts/claude_exec.py \
  --dangerously-skip-permissions \
  --session $SESSION_ID \
  --output /tmp/step1.json \
  "plan for step 1"

# Step 2 (Claude Code remembers step 1)
cd /path/to/project && python3 scripts/claude_exec.py \
  --dangerously-skip-permissions \
  --resume $SESSION_ID \
  --output /tmp/step2.json \
  "plan for step 2"
```

### When to use which pattern

| Scenario | Pattern |
|---|---|
| Quick query, small output | stdout (no `--output`) |
| Code generation, refactoring | `--output` (task file) |
| Plan exceeds ~2KB | `--plan-file` |
| Multi-step with shared context | `--session` / `--resume` |


## Result Handling

### Task file statuses

| Status | Meaning | Next action |
|---|---|---|
| `running` | Claude Code still working | Poll again |
| `completed` | Success (`exit_code: 0`) | Read `output`, verify criteria |
| `error` | Non-zero exit | Read `error`, refine plan, retry once |
| `timeout` | Exceeded `--timeout` | Split into smaller tasks or increase timeout |

### Review delegation

After receiving results, you can delegate review to a subagent for independent quality assessment:

```
"Review the following output against these acceptance criteria:
[paste criteria]

Check:
1. Are all criteria met?
2. Any regressions or code smells introduced?
3. Pass/fail verdict with explanation."
```

This provides a fresh perspective — the reviewer has no sunk cost in the implementation.


## Error Recovery

| Failure | Response |
|---|---|
| Clear error message | Refine the plan with more specifics, retry once |
| Timeout | Split task into smaller steps, or increase `--timeout` |
| Criteria unmet | Add more detailed instructions or constraints, retry |
| Two consecutive failures | **Stop.** Escalate to the user with your diagnosis |

**Rule: never retry the same plan more than twice.** If it fails twice, the plan is the problem — rethink your approach or ask the user.


## Advanced

### Restricted permissions

For environments where full permissions are inappropriate:

```bash
# Read-only analysis
python3 scripts/claude_exec.py --permission-mode plan "Analyze the architecture"

# Scoped editing
python3 scripts/claude_exec.py \
  --allowed-tools "Read,Edit(src/**),Bash(npm test)" \
  "Fix the bug and run tests"
```

| Mode | Can Read | Can Edit | Can Run Commands |
|---|---|---|---|
| `plan` | Yes | No | No |
| `acceptEdits` | Yes | Yes | No |
| `--allowed-tools` | Yes | Controlled | Controlled |

### Tool names for `--allowed-tools`

| Tool | Scoping syntax |
|---|---|
| `Read` | — |
| `Edit` | `Edit(src/**)` |
| `Write` | `Write(src/**)` |
| `Glob` | — |
| `Grep` | — |
| `Bash` | `Bash(npm test)` |
| `WebFetch` | — |
| `WebSearch` | — |

### CLI reference

```
python3 scripts/claude_exec.py [OPTIONS] "prompt"
```

| Option | Description |
|---|---|
| `--dangerously-skip-permissions` | Skip all permission checks (default recommendation) |
| `--plan-file PATH` | Read execution plan from file instead of command line |
| `--output FILE` | Write results to JSON task file instead of stdout |
| `--session UUID` | Create a new session with this UUID |
| `--resume ID` | Resume an existing session |
| `--continue-session` | Continue the most recent session in cwd |
| `--permission-mode MODE` | `plan`, `acceptEdits`, `dontAsk`, `default`, `bypassPermissions` |
| `--allowed-tools RULES` | Comma-separated tool allow rules |
| `--disallowed-tools RULES` | Comma-separated tool deny rules |
| `--model NAME` | `sonnet`, `opus`, `haiku`, or full model ID |
| `--max-turns N` | Limit agentic turns |
| `--max-budget N` | Limit spend in USD |
| `--output-format FMT` | `text` (default), `json`, `stream-json` |
| `--append-system-prompt TEXT` | Append instructions to system prompt |
| `--add-dir PATHS` | Comma-separated additional directories |
| `--mcp-config PATH` | MCP server configuration JSON file |
| `--timeout SECS` | Subprocess timeout (default: 600) |

Exit codes: `0` success, `124` timeout, `127` claude CLI not found.

### Troubleshooting

**"error: the following arguments are required: prompt"**
`--allowed-tools` consumed the prompt. Pass tools as a single comma-separated string:
```bash
# Wrong: --allowed-tools "Read" "Edit(src/**)" "Fix the bug"
# Right: --allowed-tools "Read,Edit(src/**)" "Fix the bug"
```

**"Invalid session ID"**
Generate a UUID: `python3 -c "import uuid; print(uuid.uuid4())"`.

**"Session ID is already in use"**
Use `--resume` instead of `--session` after the first call.

**Tools blocked despite permission mode**
`WebFetch` and `WebSearch` always require explicit `--allowed-tools` regardless of permission mode.


## Notes

- **Working directory:** Claude Code runs in the cwd where the script is invoked. Always `cd` to the target project first. Use `--add-dir` for cross-project access.
- **Session storage:** Managed by Claude Code in `~/.claude/projects/`.
- **Timeout coordination:** Your calling tool's timeout must be >= the script's `--timeout`.
- **Atomic writes:** Task files are written atomically (tmp + rename) — safe to poll.
- **Third-party models:** Configure via `ANTHROPIC_BASE_URL` / `ANTHROPIC_API_KEY` env vars. When set, `--model` is ignored.
