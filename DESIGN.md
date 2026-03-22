# Design

HaL advances collaboration through threads, grounds state in files,
and keeps humans in control.

HaL 以 thread 推进协作，以文件沉淀状态，由人决定方向与边界。
它不止于服务工作，也可以承载生活、学习与兴趣中的长期协作。

These invariants should stay stable even as the system evolves.

---

## Invariants

### 1. Thread is the unit of collaboration

HaL advances work through threads, not isolated chats. A thread carries
the state of an ongoing collaboration across sessions and time.
Continuity comes from thread state, not history replay.

### 2. Files are state, events are evidence

Durable state lives in files and directories. Runtime actions become
append-only events. If something matters, it should be inspectable,
portable, and rebuildable from the filesystem and event trail.

Context is compiled from current state, not recalled from raw chat logs.
The goal is not to remember everything, but to keep the right working set.

### 3. Human defines direction, AI advances the work

Human-in-the-loop is non-negotiable. The human sets goals, boundaries,
and triggers. The AI executes, organizes, and helps distill progress.

High autonomy inside clear boundaries. No hidden takeover of direction.

---

## Decision test

When evaluating a change:

1. Does it strengthen thread-based continuity?
2. Does it keep state in files and runtime evidence in append-only events?
3. Does it preserve human control while letting AI act effectively inside bounds?

---

## Collaboration Architecture

The invariants above shape the following concrete architecture.

### Concepts

| Concept | Role |
|---------|------|
| **Thread** | Long-lived collaboration container for an ongoing concern |
| **Session** | Focused work run, mounted on threads, producing durable evidence |
| **Turn** | Atomic collaboration cycle: human input → engine → response |
| **Event** | Granular evidence attached to a turn (durable or transient) |
| **Episode** | Immutable compaction of a session's contribution to a thread |
| **Brief** | Compiled synthesis of a thread's current state (`BRIEF.md`) |

### Session lifecycle

```
human creates session (selects primary thread + mounted threads)
  ├── turn 1 → turn N: events emitted to working-log.jsonl
  └── human ends session:
      ├── /brief → episode created → BRIEF.md updated
      └── /drop  → session dropped, no sedimentation
```

- **Membership is explicit; content is fresh.** Mounted threads are set at
  creation and modifiable mid-session. Context (BRIEF, memory, dynamic) is
  recompiled every turn — no frozen baselines.
- **Human creates and ends sessions explicitly.** No auto-creation, no
  auto-sedimentation.

### Event stream

Each session owns a monotonic `SessionEventPublisher`. Events carry
`{v, seq, ts, session_id, turn_id, type, actor, refs, payload}`.

- **Durable events** persist to `working-log.jsonl` — sufficient to
  reconstruct the session UI and feed the brief worker.
- **Transient events** (token streaming, progress) travel only over live
  connections.

### Runtime boundary

```
IM channels (Telegram)  ─── adapter ──→ MessageBus ──→ AgentEngine
Native web              ─── SessionBridge (direct) ──→ AgentEngine
```

`session_id` is the engine's sole identity key. Transport routing
(`channel:chat_id`) is a thin adapter concern. The native web server
bridges directly to engine session lifecycle — it is not a channel adapter.

### Storage layout

```
~/.hal/
  work/
    threads/{slug}/         BRIEF.md, THREAD.yaml, episodes/, refs/sessions.jsonl
    sessions/{session_id}/  manifest.json, working-log.jsonl
  runtime/
    resume/                 Engine checkpoints
    logs/                   Operational logs
    metrics/                Context metrics
```

Sessions live under `work/` — they are persistent work units, not
ephemeral runtime artifacts. Threads and sessions are linked via
`refs/sessions.jsonl`, not physical nesting.

See `docs/specs/workspace-layout.md` for the canonical workspace contract,
legacy-path cleanup policy, and the boundary between durable state and runtime
derived data.

### Frontend design

See `docs/specs/design-system.md` for the interface design system:
tokens, layout modes, component guidance, and the design checklist.

### Prompt-side message injects

See `docs/specs/message-injects.md` for the durable prompt-input contract used
for thread snapshots, per-turn context, and runtime injections that must remain
replayable across turns.

### Thread system

See `docs/specs/thread-system.md` for thread semantics, session-thread
relationships, brief worker contract, and BRIEF authoring principles.
