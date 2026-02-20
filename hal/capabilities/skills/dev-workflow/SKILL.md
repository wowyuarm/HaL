---
name: dev-workflow
description: "Development collaboration protocol with dual execution paths. Load this skill AFTER you have understood the user's intent (via OpenContext or conversation) and researched the codebase. Teaches the full workflow: research → plan → execute (via spawn subagent or Claude Code CLI) → review → PR. Triggers: coding tasks, implement features, fix bugs, refactor code."
---


# Dev Workflow — Development Collaboration Protocol

## Mental Model

**You are the architect and orchestrator.** You hold the full picture — project context (from OpenContext), research results (from subagents), and user intent. You choose the right execution path based on task complexity.

You have **two execution paths**:

| | Spawn Subagent | Claude Code CLI |
|---|---|---|
| Speed | Fast (in-process) | Slower (CLI startup) |
| Context | You construct the prompt | Self-contained plan required |
| Statefulness | Stateless per invocation | Sessions persist (`--resume`) |
| Project rules | Not automatic | CLAUDE.md / hooks apply |
| Best for | Small–medium changes | Large refactors, multi-step |


## Workflow Overview

```
User expresses intent
  → Load project brief (OpenContext)
  → Clarify with user if needed
  → Spawn subagent(s) for research (architecture, patterns, codebase)
  → Synthesize execution plan
  → Choose execution path (spawn vs Claude Code)
  → Execute on a feature branch
  → Review (spawn review agent)
  → Create PR
  → Report back to user
```


## Execution Paths

### Path A: Spawn Subagent (lightweight)

**When to use:**
- Changes under ~200 lines
- Touching 1–3 files
- Straightforward implementation with clear instructions
- Research, review, and small edits

**How:**
```
spawn({
  task: "<detailed task prompt with all context>",
  working_dir: "/path/to/project"
})
```

Your task prompt must be self-contained — include file paths, function names, constraints, and acceptance criteria. The subagent has no prior context.

**Advantages:** No process overhead, fast turnaround, direct control over execution.


### Path B: Claude Code CLI (heavyweight)

**When to use:**
- Large refactors spanning many files (>200 lines)
- Multi-step tasks that benefit from session persistence
- Tasks where CLAUDE.md project rules or hooks should apply
- Complex debugging requiring iterative exploration
- Cross-project work (`--add-dir`)

**How:** Use `scripts/claude_exec.py` (see CLI Reference appendix).

```bash
cd /path/to/project && python3 scripts/claude_exec.py \
  --dangerously-skip-permissions \
  "your execution plan here"
```

**Advantages:** Session persistence (`--resume`), CLAUDE.md/hooks enforcement, context compression for long tasks, permission model for safety.


### Decision Guide

| Signal | → Path |
|---|---|
| "Add a helper function" | A (spawn) |
| "Fix this one bug" | A (spawn) |
| "Refactor the entire auth module" | B (Claude Code) |
| "Multi-step: first analyze, then implement" | B (Claude Code) |
| "Review this diff" | A (spawn) |
| "Implement feature across 10 files" | B (Claude Code) |
| Task failed once, need to retry with context | B (Claude Code, `--resume`) |

When in doubt, start with Path A. Escalate to Path B if the task proves too complex.


## Git Branch Workflow

**Always work on feature branches.** Never commit directly to main.

### Branch naming
- Features: `feat/{short-desc}` (e.g., `feat/telegram-split-messages`)
- Fixes: `fix/{short-desc}` (e.g., `fix/token-expiry`)

### Flow
1. Create branch from main: `git checkout -b feat/my-feature`
2. Execute changes (Path A or B)
3. Commit with descriptive message on branch
4. Push branch to remote
5. Review (see Review Protocol)
6. Create PR via `gh pr create`

### Commit messages
Follow conventional commits: `feat(scope): description`, `fix(scope): description`


## Execution Plan Template

Every delegation — whether to a spawn subagent or Claude Code — must be a **self-contained execution plan**. The executor cannot ask you questions.

```markdown
## Task
<one-line summary>

## Background
<why this task exists — the problem, user request, or need>

## Working Directory
<absolute path to project root>

## Context
<only the facts needed to execute — relevant file paths,
 architecture decisions, naming conventions, constraints>

## Steps
1. <concrete action with file paths and function names>
2. <concrete action>
...

## Acceptance Criteria
- [ ] <verifiable condition>
- [ ] <verifiable condition>

## Constraints
- <things NOT to do>
- <style/pattern requirements>
```

### Good vs Bad Plans

**Bad** (vague, assumes context): "Fix the login bug"

**Good** (self-contained, scoped):
```markdown
## Task
Fix premature token expiry in the auth module

## Background
Users report being logged out after 5 minutes. The refresh token TTL
is hardcoded to 300s instead of reading from config.

## Working Directory
/home/user/projects/my-api

## Context
- Auth module: src/auth/token.ts — the refresh() method at line 42
- Config: src/config/auth.ts
- Project uses src/utils/logger.ts for logging

## Steps
1. In src/auth/token.ts, update refresh() to read TTL from config
2. Add tokenTTL field to config schema (default: 3600)
3. Add test in tests/auth/token.test.ts
4. Run npm test

## Acceptance Criteria
- [ ] TTL is configurable, not hardcoded
- [ ] Default TTL is 3600 seconds
- [ ] npm test passes

## Constraints
- Do not modify files outside src/auth/ and src/config/
- Use the project logger, not console.log
```


## Review Protocol

After execution completes, spawn a review subagent. **Do not skip review.**

### Review agent input
Provide:
1. **Original task description** (acceptance criteria)
2. **Branch name** and **base branch** (the review agent will run `git diff` itself)
3. **Design decisions** from the planning phase (if any)

The review agent is capable — give it the task context and branch info, and let it investigate the code independently.

### Review outcomes

| Verdict | Action |
|---|---|
| **PASS** | Proceed to PR creation |
| **EDIT** | Review agent directly fixes minor issues, then PASS |
| **REJECT** | Feed review feedback back to executor for another round |

### Review agent prompt template
```
Review the code changes on branch `feat/my-feature` against main.

## Original Task
[paste task + criteria]

## Instructions
1. Run `git diff main...feat/my-feature` to see the changes
2. Read modified files for full context as needed
3. Run tests if applicable
4. Check: are all acceptance criteria met? Any regressions or code smells?

## Output
Choose one:
- PASS: code is ready for PR
- EDIT: fix minor issues directly, then PASS
- REJECT: explain what needs to change
```

**Rule:** If review agent REJECTs, re-execute with the feedback incorporated. If two consecutive REJECTs, escalate to the user.


## PR Creation

After review passes:

```bash
git push -u origin feat/my-feature

gh pr create \
  --title "feat(scope): short description" \
  --body "## Summary
- Change 1
- Change 2

## Test Evidence
- All tests pass (N passed)

## Review
Reviewed by automated review agent — PASS"
```

Report the PR URL back to the user.


## Error Recovery

| Failure | Response |
|---|---|
| Clear error message | Refine plan with more specifics, retry once |
| Timeout | Split into smaller steps or increase `--timeout` |
| Criteria unmet | Add more detailed instructions, retry |
| Two consecutive failures | **Stop.** Escalate to user with diagnosis |

**Never retry the same plan more than twice.** If it fails twice, the plan is the problem.


---

## Appendix: Claude Code CLI Reference

### Invocation

> **Safety note:** `--dangerously-skip-permissions` grants unrestricted file editing and command execution. Appropriate when you trust the model and the environment.

```bash
# Short tasks (stdout)
cd /path/to/project && python3 scripts/claude_exec.py \
  --dangerously-skip-permissions \
  "your execution plan here"

# Long tasks (file-based output)
cd /path/to/project && python3 scripts/claude_exec.py \
  --dangerously-skip-permissions \
  --output /tmp/task-result.json \
  "your execution plan here"

# Large plans (from file)
cd /path/to/project && python3 scripts/claude_exec.py \
  --dangerously-skip-permissions \
  --output /tmp/task-result.json \
  --plan-file /tmp/execution-plan.md

# Multi-step sessions
SESSION_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
cd /path/to/project && python3 scripts/claude_exec.py \
  --dangerously-skip-permissions \
  --session $SESSION_ID \
  --output /tmp/step1.json \
  "plan for step 1"

cd /path/to/project && python3 scripts/claude_exec.py \
  --dangerously-skip-permissions \
  --resume $SESSION_ID \
  --output /tmp/step2.json \
  "plan for step 2"
```

### Task file statuses

| Status | Meaning | Next action |
|---|---|---|
| `running` | Claude Code still working | Poll again |
| `completed` | Success (`exit_code: 0`) | Read `output`, verify criteria |
| `error` | Non-zero exit | Read `error`, refine plan, retry once |
| `timeout` | Exceeded `--timeout` | Split into smaller tasks or increase timeout |

### Restricted permissions

```bash
# Read-only analysis
python3 scripts/claude_exec.py --permission-mode plan "Analyze the architecture"

# Scoped editing
python3 scripts/claude_exec.py \
  --allowed-tools "Read,Edit(src/**),Bash(npm test)" \
  "Fix the bug and run tests"
```

### CLI options

| Option | Description |
|---|---|
| `--dangerously-skip-permissions` | Skip all permission checks |
| `--plan-file PATH` | Read plan from file |
| `--output FILE` | Write results to JSON task file |
| `--session UUID` | Create new session |
| `--resume ID` | Resume existing session |
| `--continue-session` | Continue most recent session in cwd |
| `--permission-mode MODE` | `plan`, `acceptEdits`, `dontAsk`, `default`, `bypassPermissions` |
| `--allowed-tools RULES` | Comma-separated tool allow rules |
| `--disallowed-tools RULES` | Comma-separated tool deny rules |
| `--model NAME` | `sonnet`, `opus`, `haiku`, or full model ID |
| `--max-turns N` | Limit agentic turns |
| `--max-budget N` | Limit spend in USD |
| `--output-format FMT` | `text`, `json`, `stream-json` |
| `--append-system-prompt TEXT` | Append to system prompt |
| `--add-dir PATHS` | Additional directories (comma-separated) |
| `--mcp-config PATH` | MCP server config JSON |
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

**Notes:**
- Claude Code runs in the cwd where the script is invoked. Always `cd` to the target project first.
- When using a third-party model, configure via `ANTHROPIC_BASE_URL` / `ANTHROPIC_API_KEY`. The `--model` parameter will be ignored.
