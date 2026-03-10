# Design

HaL advances collaboration through threads, grounds state in files,
and keeps humans in control.

HaL 以 thread 推进协作，以文件沉淀状态，由人决定方向与边界。
它不止于服务工作，也可以承载生活、学习与兴趣中的长期协作。

These are the project's invariants. They should stay stable even as
the system evolves.

---

## 1. Thread is the unit of collaboration

HaL advances work through threads, not isolated chats. A thread carries
the state of an ongoing collaboration across sessions and time.
Continuity comes from thread state, not history replay.

## 2. Files are state, events are evidence

Durable state lives in files and directories. Runtime actions become
append-only events. If something matters, it should be inspectable,
portable, and rebuildable from the filesystem and event trail.

Context is compiled from current state, not recalled from raw chat logs.
The goal is not to remember everything, but to keep the right working set.

## 3. Human defines direction, AI advances the work

Human-in-the-loop is non-negotiable. The human sets goals, boundaries,
and triggers. The AI executes, organizes, and helps distill progress.

High autonomy inside clear boundaries. No hidden takeover of direction.

---

## Decision test

When evaluating a change:

1. Does it strengthen thread-based continuity?
2. Does it keep state in files and runtime evidence in append-only events?
3. Does it preserve human control while letting AI act effectively inside bounds?
