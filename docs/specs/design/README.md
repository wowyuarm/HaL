# HaL Web Design Docs

Status: Active

This directory splits HaL Web design documentation by abstraction layer so `docs/specs/design-system.md` can stay principle-first instead of absorbing every surface and implementation rule.

These docs are active and normative within their stated ownership boundaries. Start from `../design-system.md`, then use the owning layer doc for the exact rule you need.

## Doc map

| Layer | Purpose | Canonical doc |
| --- | --- | --- |
| L0 | Product/domain contracts owned outside design docs | `../thread-system.md`, `../message-injects.md`, `../workspace-layout.md` |
| L1 | Experience principles, identity, non-goals | `../design-system.md` |
| L2 | Surface information architecture and reading flow | `surface-spec.md` |
| L3 | Visual foundations: color, type, spacing, depth, radius, motion | `design-tokens.md` |
| L4 | Interaction and component grammar | `component-spec.md` |
| L5 | State semantics and event rendering rules | `state-and-event-spec.md` |
| L6 | Terminology, naming, copy boundaries | `glossary.md` |

## Start here by task

- I need the overall design posture → `../design-system.md`
- I need exact terms and naming boundaries → `glossary.md`
- I’m implementing a page or review surface → `surface-spec.md`
- I need token values or usage constraints → `design-tokens.md`
- I’m building or refactoring a component → `component-spec.md`
- I need state expression or event-rendering rules → `state-and-event-spec.md`

## Ownership rules

- Each concern should have one canonical home.
- `design-system.md` stays stable and low-churn.
- `design-system.md` remains the main entrypoint, but it is not the only active design spec.
- The owning layer doc is authoritative for detailed behavior inside its scope.
- Product/domain truth does not get redefined here; link back to L0 docs instead.
- If a rule is page-specific or implementation-dense, it should not live in `design-system.md`.
- If a rule is about state expression or evidence rendering rather than page layout, it belongs in L5, not L2.
- If a term is not valid product vocabulary, mark it as implementation-only in `glossary.md`.

## Structural acceptance gates

The split is structurally solid when all of the following are true:

1. No unresolved blocking terminology decisions remain in `glossary.md`.
2. No spec references undefined tokens.
3. No normative rule text is duplicated across layers without a clear owner.
4. Each file's `Owns / Does not own` boundary matches its actual contents.
5. New work can answer "where does this rule belong?" without reopening the whole split.
