# Tool System

**Status:** Draft

Tools are HaL's interface with durable state and the surrounding environment.
They translate intent into side effects and translate results back into
consumable context. Their design must serve collaborative intelligence — not
default to code manipulation.

This document defines the contracts, layers, and design principles for how
tools are defined, described, assembled, and surfaced to the model.

## Why This Exists

HaL operates through tools. Every file read, every search, every shell command,
every message sent is a tool call. This makes the tool surface the single most
influential factor in shaping HaL's default behavior — more than instructions,
more than persona, more than any individual prompt.

A tool surface biased toward code editing produces a coding agent. A tool
surface biased toward file I/O produces a file-manipulation agent. Neither is
what HaL should be. HaL is a collaborative intelligence whose tools should
serve durable-state collaboration: understanding context, advancing threads,
producing evidence, and interacting with the environment when doing so moves
the work forward.

The tool system must therefore be designed with the same care as the thread
system or the context compilation pipeline — it is not an implementation
detail but an architectural surface.

## Core Principles

1. **Tools shape behavior.** The set of available tools, their naming, their
   descriptions, and their defaults collectively define HaL's action space.
   Action space determines what HaL reaches for first. Design the tool surface
   to make the right first move natural.

2. **Single-verb tools.** Each tool should represent one cognitive action with
   one clear verb. A model choosing between `read`, `edit`, and `bash` spends
   less overhead than a model choosing `fs(action="read")` vs
   `fs(action="edit")`. Cognitive tax compounds across every tool call in
   every turn.

3. **Tool prompts are part of the harness.** A tool is not fully described by
   its parameter schema. Each tool carries a prompt — guidance on when to use
   it, when not to, what defaults to prefer, and what to avoid. This prompt
   enters the model context as part of the tool description and directly
   shapes behavior.

4. **Two layers of guidance.** Tool prompts handle operational correctness
   (how to use this tool well). System instructions handle behavioral shaping
   (how to work as a collaborative intelligence). Tools say what they can do;
   instructions say how HaL should work. Do not mix these concerns.

5. **Bash is an execution environment, not a catch-all.** Shell execution is
   powerful but noisy. Bash should be equipped with agent-friendly
   infrastructure commands and guided by its tool prompt to prefer them. It
   should not be the default path for operations that have dedicated tools.

6. **Output is context.** Every tool result enters the model's working set and
   consumes token budget. Tools should produce the minimum output needed to
   inform the next decision. Built-in guardrails (pagination, truncation,
   relative paths, ignore rules) are not optional niceties — they are
   context hygiene.

7. **Discovery before action.** The natural workflow is: discover what exists →
   understand what is relevant → read what matters → act on what needs
   changing. The tool surface should make this progression easy and natural,
   not force HaL to jump straight to reading or modifying.

## Tool Anatomy

Every tool has three layers:

### Schema

The parameter contract. Defines name, parameter types, constraints, and
required fields. This is what the model sees as the callable interface.

### Prompt

Per-tool guidance that enters the model context as part of the tool
description. Covers:

- when to use this tool (and when to prefer alternatives)
- default behaviors and recommended patterns
- common mistakes to avoid
- infrastructure commands available (for bash)
- output characteristics the model should expect

The prompt is not documentation for a human developer. It is behavioral
guidance for the model at decision time.

### Implementation

The execution logic. Handles parameter validation, path resolution,
safety guards, output formatting, and side-effect tracking. Not visible
to the model.

## Tool Categories

### Durable-State Primitives

Tools that interact with the filesystem as HaL's persistent state layer.

- **read** — Read file contents with optional offset and limit. The primary
  way to inspect durable state.
- **write** — Create or overwrite a file. Produces new durable state.
- **edit** — Precise text replacement in an existing file. Modifies durable
  state with minimal disruption.

These are not "coding tools." Files in HaL's world include briefs, thread
metadata, memory, research notes, configuration, and code. The verbs are
the same because the substrate is the same.

### Execution

- **bash** — Shell execution with agent-friendly infrastructure. Not a raw
  shell but an equipped environment with known available commands
  (search, discovery, structured extraction, version control, build/test)
  and guidance on how to use them well.

  Bash subsumes what would otherwise be many small tools (grep, glob, find,
  tree, git operations, test runners, linters). The tradeoff is flexibility
  over guardrails — bash output is less controlled than dedicated tools, so
  infrastructure commands and output compression help compensate.

### Network

- **web_search** — Search the web for information.
- **web_fetch** — Fetch and extract content from a URL.

### Collaboration

- **message** — Send a message to the human through a channel.
- **spawn** — Delegate a bounded task to a subagent.
- **recall** — Semantic search over episode memory.

## Bash Infrastructure

Bash is not a bare shell. It is an execution environment equipped with
agent-oriented commands. The bash tool prompt should make these known and
guide their use.

### Available Infrastructure

The following categories of infrastructure commands should be documented in
the bash tool prompt when they are available in the environment:

- **Content search** (e.g., ripgrep) — search within files by pattern
- **File discovery** (e.g., fd) — find files by name, type, recency
- **Structured extraction** (e.g., jq, yq) — precise JSON/YAML queries
- **Output compression** (e.g., rtk) — token-optimized command output
- **Version control** (e.g., git) — repository operations
- **Build and test** (e.g., pytest, ruff) — verification commands

### Infrastructure Principles

1. Prefer structured commands over raw text manipulation. Use content
   search tools over `grep`, file discovery over `find`, structured
   extraction over `awk`/`sed`.
2. Prefer commands that produce bounded, predictable output. Use result
   limits, line truncation, and output modes that reduce noise.
3. When output compression infrastructure is available, use it for
   commands known to produce verbose output (diffs, test results, linter
   output).
4. Do not use bash for operations that have dedicated tools. File reading
   belongs to `read`, file modification belongs to `edit`/`write`.

## Prompt Assembly

Tool prompts participate in context assembly but are not part of the system
prompt. They are attached to the tool definition that the model receives,
as the tool description field.

This means:

- Tool prompts travel with the tool schema, not with the system prompt layers.
- Adding, removing, or modifying a tool automatically adjusts the guidance
  the model sees.
- System prompt remains focused on identity, capabilities overview, situation,
  and behavioral shaping — not per-tool operational details.
- Prompt cache stability is preserved because tool definitions are a stable
  part of the API call.

Cross-tool orchestration guidance (e.g., "discover before acting," "prefer
read over bash for file contents") belongs in system instructions, not in
any single tool prompt.

## Side Effects and Evidence

Tools that modify state report their side effects:

- File tools report paths modified.
- Bash reports commands executed.
- Message reports deliveries.
- Spawn reports delegated tasks.

These side effects feed into session event tracking, memory hooks, and the
working log. They are the evidence trail that makes tool use inspectable
and auditable.

## Effect on Other Systems

- **Context builder** assembles tool definitions (schema + prompt) as part of
  the API call, separate from the system prompt layers.
- **System instructions** carry cross-tool behavioral guidance without
  duplicating per-tool details.
- **Subagent prompts** may carry a different tool prompt configuration
  appropriate to the subagent's bounded task.
- **Session events** record tool calls and their side effects as durable
  evidence.
- **Working log** reflects tool-call events for later inspection by brief
  workers and UI.
