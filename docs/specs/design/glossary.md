# HaL Web Glossary

Status: Active
Layer: L6 terminology and naming

This file defines the canonical vocabulary contract for HaL Web. It separates product-facing terms, system/domain terms, and implementation-only aliases.

## Vocabulary contract

### Product-facing terms

Use these in UI copy, design docs, and product discussions unless a lower-level concept is explicitly required.

- **Thread** — long-lived collaboration container
- **Session** — focused work run inside a thread
- **Working Log** — primary readable flow of a session
- **BRIEF** — mutable compiled re-entry artifact for a thread
- **Evidence** — on-demand inspection layer attached to collaboration activity
- **Scope** — active thread context selection for a session
- **Process detail** — structured first layer inside Evidence for a turn
- **Raw events** — deepest evidence layer containing original event-level records

### System/domain terms

Use these when describing runtime structure, storage, or evidence semantics.

- **Turn** — atomic collaboration unit inside a session
- **Event** — append-only granular record attached to session/turn flow
- **Episode** — immutable session contribution record for a thread
- **primary / mounted / touched / related** — documented thread role signals

### Implementation-only aliases

Allowed in code, comments, and library integration, but not as canonical product vocabulary.

- `conversation` — internal rendering namespace; maps to Working Log, not a product object
- `message` — rendering unit for turn content; not a separate domain object
- `record` — generic implementation alias for low-level data; prefer `event` in specs and evidence copy
- `process rail` — layout term for one Process detail presentation mode; not the umbrella concept
- `recalled_threads` / `recalled threads` — implementation or diagnostics wording, not product vocabulary

## Canonical glossary

| Term | Type | Definition | Preferred UI label | Allowed aliases |
| --- | --- | --- | --- | --- |
| Thread | product + domain | Long-lived collaboration container for continuity across sessions | Thread | thread |
| Session | product + domain | Focused run inside a thread | Session | run (internal analytics only) |
| Working Log | product | Primary readable session flow | Working Log | conversation (internal only) |
| BRIEF | product + domain artifact | Mutable compiled re-entry state for a thread | Brief | thread brief (descriptive copy only) |
| Evidence | product + domain umbrella | On-demand inspection layer for process and diagnostics | Evidence | - |
| Process detail | product | Structured first evidence layer for a turn | Process detail | process rail (layout mode only) |
| Raw events | domain exposed through evidence | Original event-level records shown in the deepest inspection layer | Raw events | event records |
| Scope | product + domain | Active thread context selection for a session | Scope | mounted context |
| Turn | domain | Atomic collaboration unit inside a session | Turn (only when the unit itself matters) | message (rendering layer only) |
| Event | domain | Append-only granular record attached to turn/session flow | Event | record (internal only) |
| Episode | domain artifact | Immutable session contribution record for a thread | Episode | - |

## Naming rules

1. Use one canonical term per concept at doc level.
2. Product docs should prefer product-facing terms over storage or runtime terms.
3. If `message` appears in docs, it must be annotated as a rendering alias for turn content.
4. Deep inspection layers should stay event-centric: prefer `events` over generic `records`.
5. Do not introduce new thread-role names in UI or payloads without updating the domain contract.
6. Layout terms are not object terms. For example, `process rail` describes presentation, not the underlying object.
7. A control should be named after the artifact or surface it opens. If a session-header toggle opens BRIEF, do not label it `Thread`.
8. `recalled_threads` is implementation language only. Product-facing docs should instead describe the visible effect in user terms, such as relevant thread context.
9. Docs and artifact references use `BRIEF`; UI copy may use `Brief` when title case reads more naturally.

## Current deprecations and aliases

| Current term | Policy | Canonical direction |
| --- | --- | --- |
| Conversation (user-facing) | keep internal only | Use `Working Log` in product copy |
| Message (domain docs) | alias only | Use `Turn` for the domain object |
| Raw records | soft deprecate | Prefer `Raw events` |
| recalled threads (product-facing) | do not use | Describe relevant thread context or use documented thread-role taxonomy |
| Thread (as a BRIEF toggle label) | deprecate | Name the control `Brief` / `BRIEF`, not `Thread` |

## Decisions now frozen

1. The thread-level compiled artifact is **BRIEF** in docs and **Brief** in ordinary UI labels.
2. The session-header review toggle should be named for **Brief**, not for a vague `Thread` surface.
3. `recalled_threads` is implementation residue, not canonical product language.
4. The canonical term and default UI label for the first evidence layer is **Process detail**.

## References

- `../design-system.md`
- `../thread-system.md`
- `../workspace-layout.md`
