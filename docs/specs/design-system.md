# HaL Design System

**Date:** 2026-03-27
**Status:** Active

## Doc map

This file is the active, principle-first entrypoint for HaL Web design. Detailed rules are split by layer under [`./design/`](./design/README.md), and those layer docs are active parts of the design-system contract.

- Principles, identity, non-goals → this file
- Terms and naming boundaries → [`./design/glossary.md`](./design/glossary.md)
- Surface information architecture → [`./design/surface-spec.md`](./design/surface-spec.md)
- Visual foundations and tokens → [`./design/design-tokens.md`](./design/design-tokens.md)
- Component and interaction grammar → [`./design/component-spec.md`](./design/component-spec.md)
- State semantics and event rendering → [`./design/state-and-event-spec.md`](./design/state-and-event-spec.md)

Use this document to understand **what HaL Web is trying to be**. Use the layered docs to understand **how a given surface, component, or state should behave**.

Authority model:

- `design-system.md` owns design posture, identity, principles, and review criteria
- each linked layer doc owns the detailed rules for its stated scope
- if a detailed rule lives in a layer doc, that layer doc is the active source for that concern

---

## 1. Identity

> **Shared cognitive workspace — where human intent meets structured execution.**

HaL is not a chat app, not a note-taking app, and not a dashboard. The human directs intent; HaL executes, records, advises, and preserves evidence. The interface should make ongoing collaboration legible without becoming a noisy control surface.

Core data model:

- **Thread** — long-lived collaboration container
- **Session** — focused work run inside a thread
- **Turn** — atomic collaboration unit inside a session
- **Event** — granular evidence attached to the session/turn flow

### Core qualities

| Quality | Meaning |
| --- | --- |
| **Restrained** | Visual budget goes to content, not decoration |
| **Transparent** | Activity has evidence and can be reviewed |
| **Structured** | Visual hierarchy mirrors cognitive hierarchy |
| **Human-directed** | The human remains the source of intent |

---

## 2. Visual World

HaL's visual world is a **quiet archival worktable**.

Not a futuristic command center. Not a playful productivity app. A table covered with paper, graphite marks, metal clips, marginal notes, and durable records. Surfaces should feel mineral, papered, and slightly tactile. Emphasis should come from structure and evidence, not decoration.

Color roles in this world:

| Physical source | Design role |
| --- | --- |
| Warm paper, vellum | Base surfaces |
| Graphite, dust | Structural edges and borders |
| Oxidized teal metal | Live system state, interaction accent |
| Brass annotation tabs | Human authorship markers |
| Amber oxide | Warning, attention needed |
| Iron red | Danger, failure, destructive action |
| Moss, completion ink | Success, brief completed |

If a new component feels glossy, consumerish, or dashboard-like, it is off-system.

---

## 3. Design Principles

### 3.1 Content Over Chrome

Content dominates. Controls, containers, and metadata recede until needed. Avoid heavy framing, loud fills, persistent toolbars, and decorative paneling.

### 3.2 Hierarchy Mirrors Structure

Visual hierarchy must match the collaboration model: thread → session → turn → event. The user should identify the current information level through layout, spacing, typography, and disclosure alone.

### 3.3 Quiet by Default, Loud on Demand

Default views feel calm and compressed. Detail emerges through expansion and local emphasis.

Escalation order:

1. spacing and grouping
2. typography weight
3. border strength
4. surface change
5. color
6. motion

### 3.4 Actions Follow Context

Actions appear where they matter: near the object they affect, not in detached global toolbars. Lifecycle actions should remain contextual, and inspection should begin from the object that produced the evidence.

---

## 4. Experience Model

HaL Web is a reading-heavy, tool-integrated workspace built around two planes:

- **Primary flow** — the readable collaboration surface
- **Inspection layers** — on-demand process and evidence surfaces

At the product level, the default readable surface is the **Working Log**. Evidence exists to support understanding and auditability, but it should not dominate the primary flow by default.

The default inspection path is:

1. a structured process-oriented view of the relevant turn
2. deeper raw event inspection when needed

The durable thread-level artifact is **BRIEF**. It should read like compiled context, not a generic drawer.

Detailed behavior for surfaces, inspection layers, and event rendering lives in:

- [`./design/surface-spec.md`](./design/surface-spec.md)
- [`./design/state-and-event-spec.md`](./design/state-and-event-spec.md)
- [`./design/glossary.md`](./design/glossary.md)

---

## 5. Layout Doctrine

The base workspace is navigation plus primary content.

Review surfaces may accompany the main reading flow, but they remain secondary to it. Their exact presentation belongs to the surface spec, not to this principles document.

Layout rules at principle level:

- regions separate through spacing, width, and hairline borders rather than heavy contrast
- the navigation layer should feel quieter than the primary reading layer
- composer presence depends on whether the session is interactive
- when the composer is treated as a detached writing object, it should feel deliberate rather than boxed into generic footer chrome

Detailed layout and surface rules live in [`./design/surface-spec.md`](./design/surface-spec.md).

---

## 6. Foundations and Grammar

The design system has four lower layers beneath this document:

- **Tokens** — color, type, spacing, depth, radius, motion
- **Surface spec** — what each surface shows, hides, and prioritizes
- **Component spec** — control families, component grammar, markdown and composer rules
- **State and event mapping** — how runtime semantics become visible UI

These are separate on purpose. Principles should change slowly. Surface and implementation rules can evolve without forcing a rewrite of the whole system story.

This file stays the main entrypoint contributors should open first. Detailed rules should be added back to the owning layer doc, not duplicated here, unless the rule changes HaL's top-level design posture.

---

## 7. Non-Goals

- dashboard-like panel fragmentation
- chat-app speaker bubbles as the dominant pattern
- persistent heavy toolbars
- high-saturation status coding
- decorative shadow stacks or gradients
- over-rounded controls
- motion as personality rather than clarity

---

## 8. Review Checklist

When evaluating a new screen or component:

1. Does content dominate over chrome?
2. Does the visual hierarchy reflect thread → session → turn → event?
3. Is it calm by default with detail available on demand?
4. Are actions attached to the object they affect?
5. Is important state visible without being noisy?
6. Does it feel like an archival cognitive workspace?
7. Does it preserve the separation between readable collaboration flow and on-demand inspection?
8. If evidence exists, can the user sense it before expanding?
