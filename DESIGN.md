# Design

HaL is a stateful collaboration system built around a human partner.
It maintains persistent working context across projects and sessions,
participates as an active collaborator, and evolves through use.

These are the project's invariants — they constrain all decisions
and should not change as the system evolves.

---

## 1. Filesystem is the source of truth

Durable state lives as files and directories. Not in databases, not in
API state, not in memory. Files are inspectable, versionable, portable.
If it matters, it's a file.

## 2. Events are append-only evidence

All runtime actions become events. Upper layers derive from lower layers
and are rebuildable. The event log is the foundation — immutable, never
deleted, never rewritten.

## 3. Context is compiled, not recalled

The working set is assembled from current state — threads, skills, memory —
not from conversation history. "Knowing where things stand" over
"remembering what was said."

## 4. Human-centric collaboration

The system collaborates with humans, not replaces them. Humans define the
work world: create threads, confirm debriefs, set direction. The system
organizes and acts within that frame.

High autonomy, low overreach.

## 5. Long-term progression over episodic chat

The unit of work is a thread, not a conversation. Threads span sessions.
Continuity comes from state progression — STATE.md, episodes, memory —
not from history retention. Chat is the medium, not the work.

---

## Decision test

When evaluating a change:

1. Does it preserve files as the durable state source?
2. Does it keep events append-only and lower layers rebuildable?
3. Does it improve the compiled working set, or just expand raw history?
4. Does it respect the human's ownership of their work world?
5. Does it advance long-term work state, or just serve a single conversation?
