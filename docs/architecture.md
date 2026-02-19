# Architecture

HaL is an AI agent framework built around an async message bus that decouples chat platforms from the agent core.

## System Overview

```
Channels (Telegram/Discord/WhatsApp/Feishu)
    │
    ▼
MessageBus (async queue)
    │
    ▼
AgentEngine ──► ContextBuilder (5-layer system prompt)
    │
    ▼
run_tool_loop() ◄──► ToolRegistry ◄──► Tools (fs, exec, web, spawn, ...)
    │
    ▼
LLMProvider (LiteLLM)
    │
    ▼
generate_summary() (optional)
    │
    ▼
Response → MessageBus → Channel
```

## Execution Modes

The engine supports three modes, each with different behavioral characteristics:

| Mode | Purpose | Latency | Context |
|------|---------|---------|---------|
| **COLLAB** | Real-time user conversation | Low | Interactive, shared session |
| **ASYNC** | Background long-running tasks | N/A | Isolated context, shared memory |
| **OPERATOR** | Scheduled cron/heartbeat tasks | N/A | High signal-to-noise prompt |

Mode is determined by the message origin:
- User messages → COLLAB
- Subagent spawns → ASYNC
- Cron/heartbeat triggers → OPERATOR

## Request Lifecycle

1. **Inbound**: A channel receives a user message and publishes `InboundMessage` to the `MessageBus`.
2. **Dispatch**: The engine's `run()` loop dequeues the message.
3. **Context Assembly**: `ContextBuilder` assembles a 5-layer system prompt (see below).
4. **Tool Loop**: `run_tool_loop()` iterates LLM calls and tool executions (max 20 iterations by default).
5. **Summary** (optional): If the loop used tools with side effects, `generate_summary()` produces a concise summary.
6. **Outbound**: The engine publishes `OutboundMessage` to the bus; the originating channel delivers it.

## Context Builder (5-Layer Architecture)

The system prompt is assembled in layers. Layers 0–2 are stable across requests (maximizing prompt cache hits); layers 3–4 change per request.

| Layer | Name | Content | Stability |
|-------|------|---------|-----------|
| 0 | Identity | Agent identity and core instructions | Rarely changes |
| 1 | Personality | SOUL.md, USER.md, AGENTS.md | Per-agent instance |
| 2 | Capabilities | Tool definitions, skill descriptions | Changes when tools change |
| 3 | Memory | Episodic memory, long-term MEMORY.md | Per-request |
| 4 | Conversation | Session history + current message | Per-request |

## Runtime Components

The `hal/core/runtime/` package contains shared execution components:

### ToolCallingLoop (`loop.py`)

A hook-based loop shared by both the engine and subagent:

```python
class LoopHooks(Protocol):
    async def before_llm_call(self, messages, meta) -> None: ...
    async def on_tool_result(self, tool_call, result, meta) -> None: ...
    async def on_no_tool_calls(self, response, meta) -> str | None: ...
    async def on_loop_exhausted(self, messages, meta) -> str | None: ...
```

The engine implements hooks for mid-loop message injection and memory recording. The subagent implements hooks for force-summary on loop exhaustion.

### ToolFactory (`tool_factory.py`)

`create_tools()` builds a `ToolRegistry` with capability-based filtering:
- **Engine**: Full tool set (fs, exec, web, message, spawn, cron, recall)
- **Subagent**: Restricted set (no message, spawn, or cron to prevent recursive spawning)

### Summary (`summary.py`)

Stateless `generate_summary()` function. Serializes loop messages (truncated to fit limits) and asks the LLM for a concise summary. Used after tool-heavy interactions to provide a digestible response.

## Component Boundaries

| Component | Depends On | Depended On By |
|-----------|-----------|----------------|
| `MessageBus` | — | Engine, Channels |
| `AgentEngine` | Bus, Provider, ContextBuilder, Runtime, Memory | CLI (`gateway`, `agent`) |
| `ContextBuilder` | Memory, Skills | Engine |
| `ToolRegistry` | Tool implementations | Runtime loop |
| `MemoryManager` | DailyLog, LongTermMemory | Engine, ContextBuilder |
| `SubagentManager` | Runtime loop, ToolFactory | SpawnTool |
| `Channels` | Bus | — |
| `LLMProvider` | LiteLLM | Engine, Summary |

## Key Design Decisions

1. **Hook-based loop over inheritance**: The tool-calling loop uses a `Protocol` (structural typing) rather than class inheritance, keeping the loop logic in one place while allowing engine and subagent to customize behavior.

2. **Capability-based tool registration**: Tools are registered based on declared capabilities rather than hard-coded lists, making it easy to add new tools without modifying the factory.

3. **Stateless summary**: Summary generation is a pure function, not a method on the engine, making it testable and reusable.

4. **Path security via `relative_to()`**: File path restriction uses `Path.relative_to()` instead of string prefix matching, preventing sibling-directory bypass attacks (e.g., `/workspace-evil/` bypassing `/workspace/`).

5. **Side-effect self-declaration**: Each tool declares its own side effects via `get_side_effects()`, removing hard-coded knowledge from the engine about which tools modify state.
