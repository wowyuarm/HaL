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
  → await _execute_subagent()      ← subagent runs its own loop (up to 15 iterations)
  → return result string           ← tool_result in the SAME loop
  LLM sees tool_result → decides next step (reply / spawn more / reason further)
```

### Background (opt-in)

For long-running tasks where the main agent should respond to the user immediately.
Set `background=true` in the spawn tool call.

```
Main Agent loop iteration N:
  LLM → "call spawn(task='...', background=true)"
  → SpawnTool.execute(background=True)
  → SubagentManager.spawn_background(task)
  → asyncio.create_task()          ← fire-and-forget
  → return "Background subagent started..."
  LLM sees tool_result → replies to user immediately

        ⋮ (later, in background)

  Subagent completes → _announce_result()
  → bus.publish_inbound(channel="system")
  → Engine._dispatch → _process_system_message
  → Main agent processes result in a NEW conversation turn
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
| `hal/core/subagent.py` | `SubagentManager` — `run()` and `spawn_background()` |
| `hal/capabilities/tools/spawn.py` | `SpawnTool` — tool interface with `background` param |
| `hal/core/engine.py` | `_process_system_message()` — handles background results |
| `hal/core/context/builder.py` | `ExecutionMode.ASYNC` + `_MODE_DIRECTIVES` |

## Flow Diagram

```
User msg → Main Agent loop
              │
              LLM decides: spawn(task, background=false)
              │
              ├─ [sync, default]
              │   SpawnTool → manager.run(task) → await _execute_subagent()
              │   subagent loop: LLM ↔ tools (up to 15 iters)
              │   → result returned as tool_result
              │   → Main Agent continues in SAME loop
              │
              └─ [background, opt-in]
                  SpawnTool → manager.spawn_background(task)
                  → asyncio.create_task() → return "started..."
                  → Main Agent replies to user
                            ⋮
                  Subagent completes → bus.publish_inbound(system)
                  → Engine._process_system_message → new turn
```
