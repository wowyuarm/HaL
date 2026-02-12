# Subagent System

## Overview

Subagents are lightweight agent instances delegated by the main agent to handle
specific tasks. They share the same LLM provider but have isolated context
(no session history, no memory, no personality).

## Two Execution Modes

### Synchronous (default)

The main agent's loop **awaits** the subagent. The result flows back as a normal
`tool_result` within the same loop iteration — no bus injection, no context break.

**Benefits:**
- Prompt-cache friendly: system prompt + prior messages all hit cache
- Reasoning chain stays intact: main agent can continue, spawn more, or synthesize
- Semantically identical to other tools (exec, web_search): call → wait → continue

```
Main Agent loop iteration N:
  LLM → "call spawn(task='analyze logs')"
  → SpawnTool.execute(background=False)
  → SubagentManager.run(task)
  → await _execute_subagent()      ← subagent runs its own loop (up to 50 iterations)
  → return result string           ← tool_result in the SAME loop
  LLM sees tool_result → decides next step (reply / spawn more / reason further)
```

### Background (opt-in)

For long-running tasks where the main agent should keep working while subagents
run in parallel. Set `background=true` in the spawn tool call.

Background subagent results are **collected within the same conversation turn**:
when the main agent's LLM produces a text response (no more tool calls), the
engine awaits all pending background subagents, injects their results as
ephemeral context, and lets the LLM produce a unified final response.

**Key properties:**
- Results are **not** recorded to conversation history (ephemeral, single-turn only)
- All pending subagents are awaited together — the LLM sees all results at once
- No extra LLM round-trips per subagent (unlike the old bus-based approach)

```
Main Agent loop iteration N:
  LLM → "call spawn(task='...', background=true)"
  → SpawnTool.execute(background=True)
  → SubagentManager.spawn_background(task)
  → asyncio.create_task()          ← runs in parallel
  → return "Background subagent started..."
  LLM sees tool_result → may do more work or produce text response

Main Agent loop iteration N+k:
  LLM produces text response (no tool calls)
  → engine calls subagents.await_pending()
  → awaits all background tasks, collects (label, result) pairs
  → injects results as ephemeral user messages
  → continues loop — LLM sees all results and produces unified response
```

## Subagent Capabilities

Each subagent gets an isolated `ToolRegistry` with:
- `FsTool` — file read/write/edit/list
- `ExecTool` — shell execution
- `WebSearchTool` — web search
- `WebFetchTool` — web fetch

**Not available:**
- `spawn` — no recursive subagent creation
- `message` — no direct user messaging
- Session history or memory from the main agent

## Key Files

| File | Role |
|------|------|
| `hal/core/subagent.py` | `SubagentManager` — `run()`, `spawn_background()`, `await_pending()` |
| `hal/capabilities/tools/spawn.py` | `SpawnTool` — tool interface with `background` param |
| `hal/core/engine.py` | `_execute_loop()` — awaits pending subagents before finalizing |
| `hal/core/context/builder.py` | `ExecutionMode.ASYNC` + `_MODE_DIRECTIVES` |

## Flow Diagram

```
User msg → Main Agent loop
              │
              LLM decides: spawn(task, background=false)
              │
              ├─ [sync, default]
              │   SpawnTool → manager.run(task) → await _execute_subagent()
              │   subagent loop: LLM ↔ tools (up to 50 iters)
              │   → result returned as tool_result
              │   → Main Agent continues in SAME loop
              │
              └─ [background, opt-in]
                  SpawnTool → manager.spawn_background(task)
                  → asyncio.create_task() → return "started..."
                  → Main Agent continues working
                            ⋮
                  LLM produces text (no tool calls)
                  → await_pending() collects all background results
                  → inject as ephemeral messages → LLM unifies → final response
```
