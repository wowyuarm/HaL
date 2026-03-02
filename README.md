# HaL

> *A reliable, precise, and independent digital butler.*

Named after HAL 9000 from *2001: A Space Odyssey* — HaL is a personal AI butler that runs on your own VPS, accessed via Telegram. Always available, always precise, never overstepping.

## Philosophy

- **Reliability over cleverness** — Predictable behavior you can trust, not flashy tricks that break.
- **Precision over verbosity** — Every action is intentional; every response is grounded.
- **Independence** — Runs on your infrastructure, your data stays yours.
- **Simplicity** — Small enough to understand, powerful enough to be useful.

## Architecture

Messages flow through an async message bus that decouples the chat channel from the agent core:

```
Telegram → MessageBus (async queue) → AgentEngine → LLMProvider
                                           ↕
                                      ToolRegistry
```

### Agent Engine (`hal/core/engine.py`)

Thin coordination layer supporting 3 execution modes:

| Mode | Purpose |
|------|---------|
| **COLLAB** | Real-time user conversation (low latency, interactive) |
| **ASYNC** | Background long-running tasks (shared memory with origin) |
| **OPERATOR** | Scheduled monitoring via cron/heartbeat (high signal-to-noise) |

For each inbound message it:
1. Builds a system prompt via `ContextBuilder` (5-layer context system)
2. Delegates to `run_tool_loop()` for LLM calls and tool execution
3. Optionally generates a summary via `generate_summary()`
4. Sends the final response back through the bus

### Context Builder — 5-Layer System Prompt

| Layer | Name | Content |
|-------|------|---------|
| 0 | Identity | Stable agent identity (rarely changes) |
| 1 | Personality | Per-agent instance (SOUL.md, USER.md, etc.) |
| 2 | Capabilities | Tools + skills definitions |
| 3 | Memory | Dynamic memory (episodic + long-term, per request) |
| 4 | Conversation | Current session history + inbound message |

Layers 0–2 form a stable prefix (maximizes prompt cache hits); Layers 3–4 are dynamic per request.

### Runtime (`hal/core/runtime/`)

Shared execution components:
- **ToolCallingLoop** (`loop.py`) — Hook-based tool-calling loop used by both engine and subagent
- **ToolFactory** (`tool_factory.py`) — Capability-based tool registration
- **Summary** (`summary.py`) — Stateless post-loop summarization

### Memory System (`hal/core/memory/`)

Coordinated by `MemoryManager`:
- **DailyLog** — JSONL logs of all interactions
- **LongTermMemory** — Persistent knowledge in MEMORY.md
- **MemorySearch** — Semantic search via vector embeddings (Milvus-backed)
- **DailyExporter** — Exports daily logs to markdown for indexing

### Tool System (`hal/capabilities/tools/`)

All tools extend the abstract `Tool` class, defining `name`, `description`, `parameters` (JSON Schema), `execute()`, and optionally `get_side_effects()`.

Built-in tools: `fs` (file operations), `exec` (shell), `web_search`, `web_fetch`, `recall` (semantic memory), `spawn` (subagent), `cron` (scheduling), `message` (cross-channel).

### Provider Registry (`hal/infra/providers/registry.py`)

Declarative `ProviderSpec` tuples — no if-elif chains. All providers use `LiteLLMProvider` as the unified implementation. For OpenAI-compatible proxies, set `compat_mode: "openai"`.

## Design Decisions

- **Async-first** — All I/O is async (`asyncio`), enabling concurrent tool execution and channel handling.
- **Message bus decoupling** — Channels know nothing about the agent; the agent knows nothing about channels. The bus mediates.
- **Hook-based loop** — The tool-calling loop is customized via `LoopHooks` protocol, allowing engine and subagent to share the same loop with different behaviors.
- **Prompt cache optimization** — The 5-layer context system keeps layers 0–2 stable across requests to maximize LLM prompt cache hits.
- **Workspace sandbox** — When `restrict_to_workspace=true`, file and shell tools are sandboxed to the workspace directory.

## Configuration

Config is split into two YAML files under `~/.hal/`:

**`config.yaml`** — Structure and settings:
```yaml
agents:
  defaults:
    model: "anthropic/claude-opus-4-5"
    max_tokens: 8192
    max_tool_iterations: 20

channels:
  telegram:
    enabled: true
    allow_from: ["YOUR_USER_ID"]

tools:
  restrict_to_workspace: false
  exec:
    timeout: 60
  web:
    search:
      max_results: 5

memory_search:
  enabled: false
  exclude_channels: ["cron"]  # prevent cron sessions from entering recall index

scheduling:
  cron:
    summary_window: 5
```

**`auth.yaml`** — Secrets (gitignored):
```yaml
providers:
  openrouter:
    api_key: sk-or-v1-xxx

channels:
  telegram:
    token: YOUR_BOT_TOKEN

tools:
  web:
    search:
      api_key: tvly-xxx  # Tavily
```

## Running

```bash
# Start the gateway (production entry point)
hal gateway

# AnyRouter bridge (local Node relay for TLS compatibility)
hal anyrouter bridge

# Cron management
hal cron add --name "daily" --message "Good morning!" --cron "0 9 * * *"
# Delivery is set per job at creation time (not global config):
# hal cron add ... --deliver --channel telegram --to <chat_id>
hal cron list
hal cron remove <job_id>
```
