# HaL Web Component Spec

Status: Active
Layer: L4 interaction and component grammar

This file owns reusable component-level behavior and grammar.

## Scope

Owns:
- control families and interaction grammar
- selectable row behavior
- markdown rendering contract
- composer grammar
- contextual row-action behavior

Does not own:
- brand principles
- page IA
- raw token values
- event-to-surface mapping

## 1. Component posture

Components should feel like objects on an archival worktable — paper cards, clipped ledger headers, inset record wells — not generic SaaS widgets.

## 2. Control families

### 2.1 Contextual controls

Controls subordinate to content: navigation toggles, inline actions, sheet close buttons, icon buttons.

Rules:
- Rest: transparent background, `--hal-text-muted`, optional hairline border
- Hover: text promotes to `--hal-text`, border promotes to `--border-default`
- No background change by default
- These controls are furniture: present and reachable, never attention-seeking
- In overflow menus, semantic escalation should usually happen through text color only

### 2.2 Primary action

- `--color-accent` fill, `--text-on-accent` text
- No shadow
- Maximum one primary action per visible context
- Reserved for the single most important action in scope

### 2.3 Secondary action

- Bordered with `--surface-paper` fill
- Clearly bounded without becoming loud
- Appropriate for cancel, scope, and similar supporting actions

### 2.4 Destructive ghost

- Transparent at rest
- Hover reveals `--color-danger` accent
- Warning should come from semantic escalation, not heavy fill

## 3. Selectable rows

Thread rows, session rows, and dialog choice rows share one interaction grammar.

| State | Background | Text | Marker |
| --- | --- | --- | --- |
| Rest | transparent | muted | — |
| Hover | `--surface-hover` | primary | — |
| Selected | `--hal-selection` | primary | left accent seam 2px |

Rules:
- Hover and selected must remain visually distinguishable.
- Hover is lighter than selected.
- `--surface-elevated` / `--hal-float` is reserved for floating UI, not inline hover or selected states.
- Row-level contextual actions appear only on hover or focus and stay visually subordinate to the row itself.

## 4. Interactive surface hierarchy

For inline interactive elements:
1. Rest — inherits parent surface
2. Hover — one micro-step above parent via `--surface-hover`
3. Selected — one clear step with accent tint via `--hal-selection`

## 5. Shadow rules

| Object | Shadow | Rationale |
| --- | --- | --- |
| Buttons | none | fill and border are sufficient |
| Inline rows and cards | none | border is the primary depth device |
| Scroll-anchored elements | `--shadow-sm` | sits above scrolling content |
| Floating UI | `--shadow-popover` | true floating layer |

Shadow on `--surface-base` or `--surface-raised` without a floating context is a design error.

## 6. Composer grammar

The composer is a writing surface, not a detached upload bar plus input field.

### 6.1 Composer shell

- The composer may act as a detached primary writing object.
- Attachment previews sit inside the composer shell, above the text row.
- Attachment and send controls stay on a dedicated action row aligned to the same inset as the writing area.
- Avoid nested bordered objects unless the workflow truly needs another containment level.

### 6.2 Attachment grammar

- Default preview grammar is compact and low-noise.
- Keep file name and format; avoid extra type badges or nested preview cards.
- Thumbnails are optional, not default.
- Composer and user-message attachments should share one compact grammar. The composer version may expose remove controls; the message version should not.
- On narrow screens, previews wrap before the text row grows taller than necessary.

## 7. Markdown and embedded content

Markdown is a first-class reading surface, not a browser default and not a generic `prose` dump.

Rules:
- Use a shared markdown renderer so assistant messages, user messages, and BRIEF do not drift.
- Clear first-child and last-child margins inside bounded containers.
- Inline code should read like an in-sentence annotation: subtle surface, warm text emphasis, no decorative pill styling.
- Code blocks use a restrained inset surface, no shadow, and no persistent toolbar chrome. Copy affordance may appear on hover only.
- Tables are reading objects, not cards: full available width, horizontal rules only, no outer box, no hover theatrics.
- External links open in a new tab and use understated underline treatment.
- Internal thread-episode links inside BRIEF or episode markdown should stay in-app and open the shared review surface.
