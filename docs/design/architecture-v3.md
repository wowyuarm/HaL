# Architecture v3: Stateful Collaboration Kernel

> Status: draft guidance for implementation batches after Context System v2.

## Core Thesis

HaL is not a "chatbot with memory".

HaL is a stateful collaboration kernel built on:

- append-only events as the write protocol
- filesystem state as the source of truth
- compiled working sets as the read protocol

The system should optimize for "knowing where work stands", not "remembering what was said".

## North Star

1. Filesystem is the source of truth
   Persist durable state as explicit files and directories, not hidden runtime objects.
2. Events are append-only evidence
   Runtime actions first become events; higher layers are rebuildable from lower layers.
3. Context is compiled, not recalled raw
   HaL should consume a working set assembled from current state, not ad hoc slices of old chat.
4. Stable context beats repeated reinjection
   Prefer a stable prefix, one session baseline, frozen checkpoints, and a small live tail.
5. Semantics and mechanisms stay separate
   `Thread` and `Skill` are different semantic objects even if they share loading machinery.
6. Human world-model mutations stay explicit
   The system may organize and suggest, but it must not silently redefine the user's work world.

## Semantic Objects

| Object | Role | Persistence | Notes |
|--------|------|-------------|-------|
| `Session` | write unit | ephemeral + logged | continuous interaction window |
| `Thread` | work unit | persistent | long-running workstream |
| `Episode` | retrieval unit | persistent | immutable session compaction for one or more threads |
| `MemoryFact` | stable knowledge | persistent | long-lived preferences/facts only |
| `Skill` | capability unit | persistent | static instructions and optional scripts |
| `Artifact` | output unit | persistent | reports, media, generated files |
| `Event` | evidence unit | append-only | lowest-level runtime fact |

## System Layers

### 1. Domain Layer

Defines what exists in HaL's world:

- sessions
- threads
- episodes
- memory facts
- skills
- artifacts

This layer owns meaning, not transport, storage, or provider details.

### 2. Runtime Layer

Defines how work flows:

- event bus
- main loop
- hooks
- advisor
- debriefer
- compactor
- background resume

This layer owns protocol and orchestration.

### 3. Context Layer

Defines how HaL receives a working set:

- registries
- context compiler
- loading policy
- recall injection
- frozen checkpoints
- live tail management

This layer is the read path for cognition.

### 4. Workspace Layer

Defines how durable state is persisted:

- event log repo
- session repo
- thread repo
- episode repo
- memory repo
- artifact repo

This layer owns files, paths, indexing roots, and rebuildability.

### 5. Interface / Infra Layer

Defines external boundaries:

- Telegram / CLI / future channels
- model providers
- vector store
- config and auth
- external tools

This layer should not define core semantics.

## Context Working Set

Each session should be assembled from four layers:

1. `Stable Prefix`
   identity, instructions, stable memory, skill registry, thread registry
2. `Session Baseline`
   one compiled context block created once at session start
3. `Frozen Checkpoints`
   compacted summaries of older turns, stable after creation
4. `Live Tail`
   recent full-fidelity turns and tool results

### Working Set Rules

- The stable prefix is immutable within a session.
- The session baseline is compiled once and reused.
- Later `STATE.md` / `SKILL.md` loads append to the working set instead of replacing the baseline.
- In-session compaction should convert older turns into frozen checkpoints, not rewrite the prefix.
- Raw tool outputs remain in events and artifacts even when the working set stores only compacted forms.

## Shared Loading Abstraction

`Thread` and `Skill` should stay semantically distinct, but share a loading contract.

Suggested abstraction:

```text
ContextUnit
  - manifest()
  - describe()
  - load()
  - priority()
  - related()
```

Possible implementations:

- `SkillUnit`
- `ThreadUnit`
- later: `ReferenceUnit`, `MemoryUnit`

This keeps the context compiler generic without collapsing all concepts into one type.

## Workspace v3

```text
~/.hal/
  system/
    SOUL.md
    INSTRUCTIONS.md
    MEMORY.md
    config.yaml
    auth.yaml

  work/
    threads/
      <thread-slug>/
        THREAD.yaml
        STATE.md
        episodes/
    inbox/

  runtime/
    logs/
      events.jsonl
    sessions/
    metrics/
    cache/

  capabilities/
    skills/

  data/
    vectors/
    artifacts/
    media/

  projects/
```

### Workspace Rules

- `THREAD.yaml` is machine-oriented registry truth.
- `STATE.md` is human/model-oriented working truth.
- `runtime/` contains rebuildable operational data.
- `system/` contains stable instruction and identity material.
- `capabilities/` stores reusable abilities, not active work state.

## Immediate Correctness Priorities

These should be fixed before deeper package reorganization:

1. Session baseline
   Stop persisting per-turn dynamic XML into conversation history.
2. Background resume persistence
   Resumed turns must update in-memory session history and the unified event log.
3. Thread touch semantics
   `touched_threads` must reflect meaningful thread usage, not only explicit `fs` path reads.
4. STATE hot-layer integrity
   Debriefing must advance `STATE.md`, not merely append timestamp notes.

## Package Reorganization Direction

Target package shape after incremental refactors:

```text
hal/
  domain/
  runtime/
  context/
  workspace/
  capabilities/
  interfaces/
  infra/
```

Migration should be staged. Do not attempt a flag-day rewrite.

## Migration Order

1. Fix correctness gaps in current v2 implementation.
2. Introduce workspace-facing repositories and reduce direct file I/O inside the engine.
3. Extract a real context compiler boundary from the engine.
4. Add machine-readable thread metadata (`THREAD.yaml`).
5. Reorganize packages around domain/runtime/context/workspace boundaries.

## Decision Test

When evaluating a change, ask:

1. Does this preserve filesystem truth as the durable state source?
2. Does this improve the compiled working set instead of expanding raw history?
3. Is this semantic-layer logic, runtime orchestration, context compilation, or infra?
4. Would this still make sense if Telegram disappeared and another interface replaced it?

If the answer to 3 is unclear, the abstraction is probably still mixed.
