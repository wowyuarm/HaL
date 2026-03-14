# HaL Design System

**Date:** 2026-03-14
**Status:** Active

---

## 1. Identity

> **Shared cognitive workspace — where human intent meets structured execution.**

HaL is not a chat app, not a note-taking app, and not a dashboard. The human
directs intent; HaL executes, records, advises, and preserves evidence. The
interface makes ongoing collaboration legible without becoming a noisy control
surface.

Core data model:

- **Thread** — long-lived collaboration container
- **Session** — focused work run inside a thread
- **Turn** — atomic unit of collaboration
- **Event** — granular evidence attached to a turn

### Core Qualities

| Quality | Meaning |
|---------|---------|
| **Restrained** | Visual budget goes to content, not decoration |
| **Transparent** | All activity has evidence, is traceable and reviewable |
| **Structured** | Visual hierarchy mirrors cognitive hierarchy; the antithesis of entropy |
| **Human-directed** | The human is always the source of intent; HaL is the medium of execution |

---

## 2. Visual World

HaL's visual world is a **quiet archival worktable**.

Not a futuristic command center. Not a playful productivity app. A table covered
with paper, graphite marks, metal clips, marginal notes, and durable records.
Surfaces feel mineral, papered, and slightly tactile. Emphasis comes from
structure and evidence, not decoration.

Color roles in this world:

| Physical source | Design role |
|----------------|-------------|
| Warm paper, vellum | Base surfaces |
| Graphite, dust | Structural edges and borders |
| Oxidized teal metal | Live system state, interaction accent |
| Brass annotation tabs | Human authorship markers |
| Amber oxide | Warning, attention needed |
| Iron red | Danger, failure, destructive action |
| Moss, completion ink | Success, brief completed |

If a new component feels glossy, consumerish, or dashboard-like, it is
off-system.

---

## 3. Design Principles

### 3.1 Content Over Chrome

Content dominates. Controls, containers, and metadata recede until needed. Avoid
heavy framing, loud fills, persistent toolbars, and decorative paneling.

### 3.2 Hierarchy Mirrors Structure

Visual hierarchy must match the data model: thread → session → turn → event.
The user should identify the current information level by layout, spacing,
typography, and disclosure alone.

### 3.3 Quiet by Default, Loud on Demand

Default views feel calm and compressed. Detail emerges through expansion and
local emphasis.

Escalation order (prefer earlier steps before reaching for later ones):

1. Spacing and grouping
2. Typography weight
3. Border strength
4. Surface change
5. Color
6. Motion

### 3.4 Actions Follow Context

Actions appear where they matter: beside the current thread, within the active
turn, adjacent to evidence, inside the BRIEF panel. No top-level toolbars that
detach actions from their object.

Lifecycle commands (`/brief`, `/drop`) remain available as slash commands in the
composer, and also surface as contextual UI affordances on the session header.
Both paths trigger the same event pipeline.

The send button uses an icon only (arrow), no label text. `Enter` sends,
`Shift+Enter` for newline.

### 3.5 State Is Always Legible

Important state is always visible, but in restrained form. Prefer dots, seams,
badges, and inline labels over banners and toast-heavy patterns.

---

## 4. Layout System

HaL uses a **mode-adaptive layout**, not a fixed three-column shell.

### 4.1 Navigation Mode

*Browsing and orienting across threads.*

- Left: thread list (~240px)
- Main: large thread detail view (BRIEF.md centered, sessions below)
- No working log visible

### 4.2 Working Mode

*Active collaboration inside a session.*

- Left: collapsed thread rail (icon-only, ~48px)
- Main: working log fills the canvas
- BRIEF: pull-out side panel (toggle or shortcut), not a permanent column

### 4.3 Review Mode

*Reading a completed session or episode.*

- Same structure as Working Mode
- Composer removed entirely (not disabled — absent)
- Reduced live-state emphasis; archival feel, not gray-out

### 4.4 Surface Rules

- The main workspace shares one base surface field
- Layout regions separate by spacing, width, and a hairline border
  (`1px solid var(--border-subtle)`) — not contrasting background color
- In Working/Review modes, the sidebar sits on the **same base surface** as the
  main canvas
- In Navigation mode, a very subtle tonal distinction for the thread list is
  acceptable

---

## 5. Color System

Two layers: **functional foundation** and **HaL semantic aliases**.

The two-layer split currently covers color and structural semantics. Component-
level semantic tokens (e.g., `--hal-turn-surface`, `--hal-brief-gap`) will be
added as components are built and patterns stabilize.

### 5.1 Foundation Tokens

```css
:root {
  color-scheme: light;

  /* Surfaces */
  --surface-base: #F7F4EF;
  --surface-raised: #EFECE6;
  --surface-elevated: #FFFFFF;
  --surface-inset: #E8E4DD;

  /* Text */
  --text-primary: #24211D;
  --text-secondary: #7A756D;
  --text-on-accent: #FFFFFF;

  /* Accent and semantic hues */
  --color-accent: #4A7A74;
  --color-accent-subtle: #E8F0EF;
  --color-human: #9A7840;
  --color-human-subtle: #F5EDE0;
  --color-danger: #A25248;
  --color-danger-subtle: #FAEAE8;
  --color-success: #5A8A6A;
  --color-success-subtle: #ECF3ED;
  --color-warning: #B8863B;
  --color-warning-subtle: #F7EFE1;

  /* Borders — rgba-based for natural blending across surfaces */
  --border-strong: rgba(36, 33, 29, 0.18);
  --border-default: rgba(36, 33, 29, 0.14);
  --border-subtle: rgba(36, 33, 29, 0.09);

  /* Semantic borders — derived from hue at lower opacity */
  --border-accent: rgba(74, 122, 116, 0.34);
  --border-human: rgba(154, 120, 64, 0.28);
  --border-danger: rgba(162, 82, 72, 0.28);
  --border-success: rgba(90, 138, 106, 0.28);
  --border-warning: rgba(184, 134, 59, 0.30);
}
```

### 5.2 Semantic Alias Tokens

```css
:root {
  /* Workspace surfaces */
  --hal-canvas: var(--surface-base);
  --hal-panel: var(--surface-raised);
  --hal-float: var(--surface-elevated);
  --hal-inset: var(--surface-inset);

  /* Text roles */
  --hal-text: var(--text-primary);
  --hal-text-muted: var(--text-secondary);

  /* State and actor semantics */
  --hal-live: var(--color-accent);
  --hal-live-subtle: var(--color-accent-subtle);
  --hal-human: var(--color-human);
  --hal-human-subtle: var(--color-human-subtle);
  --hal-danger: var(--color-danger);
  --hal-danger-subtle: var(--color-danger-subtle);
  --hal-success: var(--color-success);
  --hal-success-subtle: var(--color-success-subtle);
  --hal-warning: var(--color-warning);
  --hal-warning-subtle: var(--color-warning-subtle);

  /* Structural */
  --hal-divider: var(--border-default);
  --hal-divider-subtle: var(--border-subtle);
  --hal-focus-ring: rgba(74, 122, 116, 0.22);
  --hal-selection: rgba(74, 122, 116, 0.18);
  --hal-evidence-seam: rgba(74, 122, 116, 0.34);
}
```

### 5.3 Color Rules

- HaL output uses `--hal-text` (default). No dedicated AI color.
- Human contributions use `--hal-human` as a marker — never a large fill.
- Live/connected states use `--hal-live`.
- State colors appear first as compact markers (dots, badges, seams) before fills.
- Large fields remain neutral and paper-like.
- Avoid bright blue, neon green, or generic dashboard status palettes.

---

## 6. Typography

### 6.1 Font Families

```css
:root {
  --font-sans: "Inter", ui-sans-serif, system-ui, sans-serif;
  --font-mono: "JetBrains Mono", ui-monospace, monospace;
}
```

### 6.2 Type Scale

```css
:root {
  --type-heading-size: 18px;
  --type-heading-line: 24px;
  --type-heading-weight: 600;

  --type-subheading-size: 15px;
  --type-subheading-line: 20px;
  --type-subheading-weight: 600;

  --type-body-size: 14px;
  --type-body-line: 20px;
  --type-body-weight: 400;

  --type-meta-size: 12px;
  --type-meta-line: 16px;
  --type-meta-weight: 500;

  --type-caption-size: 11px;
  --type-caption-line: 14px;
  --type-caption-weight: 500;
}
```

| Role | Size | Weight | Line Height | Use |
|------|------|--------|-------------|-----|
| **heading** | 18px | 600 | 24px | Thread titles, major section headers |
| **subheading** | 15px | 600 | 20px | Session headings, turn headers, BRIEF sections |
| **body** | 14px | 400 | 20px | Prose, log entries, BRIEF body |
| **meta** | 12px | 500 | 16px | Timestamps, state labels, thread metadata |
| **caption** | 11px | 500 | 14px | Evidence labels, technical annotations |

### 6.3 Type Rules

- Default UI body size is 14px.
- Use weight and spacing for emphasis before reaching for color.
- Monospace is sparse and functional — code, event payloads, file paths only.
- BRIEF prose rendering may use 15–16px for reading comfort.

---

## 7. Spacing

Uses Tailwind's 4px base scale (`p-1` = 4px, `p-2` = 8px, etc.).

### 7.1 Spacing by Hierarchy Level

| Level | Internal spacing | Gap between siblings |
|-------|-----------------|---------------------|
| Event | 4–8px | 4px |
| Turn | 12–16px | 8–12px |
| Session group | 16–20px | 16–20px |
| Thread / page | 24–32px | 24–32px |

### 7.2 Density Rules

- Default density supports long working sessions without fatigue.
- Density tracks hierarchy: event items tighter than turn containers.
- Working log may be one spacing step tighter than BRIEF content.

---

## 8. Depth

Depth is expressed through **surface contrast and borders**. Shadow is rare.

### 8.1 Surface Mapping

| Surface | Color | Use |
|---------|-------|-----|
| `base` | `#F7F4EF` | Main canvas, page field |
| `raised` | `#EFECE6` | Grouped containers, navigation-mode thread items |
| `elevated` | `#FFFFFF` | Popovers, floating BRIEF panel, menus |
| `inset` | `#E8E4DD` | Composer textarea, code blocks, evidence wells |

### 8.2 Border Rules

Borders are the **primary depth and grouping device**.

- `--border-subtle`: most separators, hairline dividers
- `--border-default`: object boundaries needing clearer containment
- `--border-strong`: active or expanded objects, emphasis
- All borders are 1px solid rgba — no solid hex

### 8.3 Shadow

```css
:root {
  --shadow-sm: 0 1px 2px rgba(36, 33, 29, 0.06);
  --shadow-popover: 0 6px 18px rgba(36, 33, 29, 0.10);
}
```

- Default components: **no shadow**
- Elevated cards: `--shadow-sm` only when border alone is insufficient
- Floating elements (popovers, menus, pull-out BRIEF): `--shadow-popover`

---

## 9. Border Radius

```css
:root {
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
}
```

| Token | Use |
|-------|-----|
| 4px | Badges, tags, compact buttons, evidence fragments |
| 8px | Cards, turn containers, list items, inputs |
| 12px | Popovers, floating BRIEF, dialogs |

---

## 10. Motion

```css
:root {
  --duration-fast: 100ms;
  --duration-normal: 180ms;
  --duration-slow: 300ms;
  --ease-standard: ease-out;
}
```

### Rules

- **Fast**: hover, focus, press, small state shifts
- **Normal**: expand/collapse, panel reveal, inline status changes
- **Slow**: major layout transitions (mode switch, BRIEF pull-out)
- Motion is opacity and translate driven. No spring, bounce, or continuous
  decorative animation.
- Exception: a subtle pulse on live-state indicators is acceptable.

---

## 11. State System

### 11.1 State Semantics

| State | Token | Use |
|-------|-------|-----|
| Live / active / connected | `--hal-live` | Session active, WebSocket connected, turn processing |
| Success / completed | `--hal-success` | Brief completed, tool succeeded |
| Warning / attention | `--hal-warning` | Slow response, needs review |
| Danger / failed | `--hal-danger` | Turn failed, destructive action |
| Human-authored | `--hal-human` | Human contribution marker |

### 11.2 Expression Order

Prefer earlier forms; escalate only when needed:

1. Dot or seam color
2. Inline text label
3. Badge
4. Border tint
5. Subtle background fill
6. Banner (exceptional only)

### 11.3 Visibility Rules

- Active turns always show live state.
- Completed units show completion state without requiring expansion.
- Review mode preserves evidence of prior state but reduces live accents.
- Human ownership is visible where authorship matters, not on every line.

---

## 12. Signature Elements

### 12.1 Evidence Seam

The signature visual element. Exists at **turn level only** (for now).

Each turn may display a slim vertical seam along its leading edge:

- At rest: a quiet line indicating evidence exists, without forcing disclosure.
  May include small ticks hinting at event density.
- On expand: the seam becomes the anchor for the Evidence layer.

```css
:root {
  --turn-seam-width: 2px;
  --turn-seam-color: var(--hal-evidence-seam);
  --turn-seam-active: rgba(74, 122, 116, 0.52);
}
```

The seam is a structural signifier of evidence, not a brand flourish. It should
remain quiet until the user asks for detail.

### 12.2 BRIEF as Compiled Context

BRIEF is not a generic detail drawer. It is a compiled working artifact:

- Feels authored and durable, not generated.
- Uses elevated or raised surface depending on mode.
- Maintains strong typographic readability at lower density than the working log.

---

## 13. Working Log: Dual Layer

### 13.1 Activity Layer (default)

Optimized for scanning and momentum:

- Human prompts and direction
- HaL responses and key outputs
- Tool result summaries (not raw payloads)
- Turn-level state markers
- Failure summaries

System events (`context.compiled`, `loop.iteration`) are **not shown** in this
layer.

### 13.2 Evidence Layer (expanded)

Revealed per-turn via the evidence seam:

- Full event list with timestamps
- Tool inputs and outputs
- File change details
- Execution traces and diagnostics
- Uses inset surfaces and monospace text

### 13.3 Escalation Rules

- Evidence is entered through explicit expansion, never auto-expanded.
- During an active turn, light hints show evidence accumulating.
- When collapsed, a compact indicator conveys what kind of evidence exists.

---

## 14. Component Guidance

Components should feel like objects on the archival worktable — paper cards,
clipped ledger headers, inset record wells — not generic SaaS widgets.

### Thread List Item

The thread list reads like an **index of filed folders**. Each item shows the
thread name, a compact activity indicator, and session count. No heavy
decoration. In Navigation mode, the selected item uses `--border-default` left
accent; in Working mode (collapsed rail), only an icon with a dot state.

### Session Header

Reads like a **clipped ledger header** pinned to the top of the working log.
Shows session status (dot + label), mounted thread tags, and contextual lifecycle
actions. Keep it single-line or two-line max. Status dot uses state colors.

### Turn Container

The core collaboration object in the working log.
`--radius-md` (8px) default. Evidence seam on the leading edge when evidence
exists. Local actions appear on hover/focus, not as persistent chrome.

### Activity Row

A single entry in the Activity layer. Human entries may carry a subtle
`--hal-human` left border accent. HaL entries use default text on base surface.
Tool summaries use `meta`-sized text. Failures use `--hal-danger` border accent.

### Evidence Block

Reads like an **inset record well** — a recessed area of precise, inspectable
data. Uses `--surface-inset` background, monospace text, `--radius-sm` (4px).
Timestamps in `caption` size. Event type labels as low-contrast badges.

### Buttons and Controls

- Controls are quiet and local.
- Most actions read as contextual text buttons or icon buttons.
- Primary accent buttons are rare — only for the most important action in view.
- Avoid heavy button bars at page scope.

### Turn Container

- The core collaboration object in the working log.
- `--radius-md` (8px) default.
- Evidence seam on the leading edge when evidence exists.
- Local actions appear on hover/focus, not as persistent chrome.

### Status Badge

- Compact, `meta`-sized text.
- Border or subtle fill before saturated background.
- Stronger fills reserved for warning/danger that need immediate attention.

### Composer

- Belongs to Working mode only. Absent in Review mode (not disabled — removed).
- Minimal: textarea + icon send button.
- Slash command autocomplete is the only "smart" affordance.
- Inset surface (`--surface-inset`) for the textarea.

### Dialogs and Popovers

- `--radius-lg` (12px) for floating elements.
- `--shadow-popover` for depth.
- Elevated surface.
- Header / body / footer structure.

---

## 15. Non-Goals

- Dashboard-like panel fragmentation
- Chat-app speaker bubbles as the dominant pattern
- Persistent heavy toolbars
- High-saturation status coding
- Decorative shadow stacks or gradients
- Over-rounded controls
- Motion as personality rather than clarity

---

## 16. Design Checklist

When evaluating a new screen or component:

1. Does content dominate over chrome?
2. Does the visual hierarchy reflect thread → session → turn → event?
3. Is it calm by default with detail available on demand?
4. Are actions attached to the object they affect?
5. Is important state visible without being noisy?
6. Does it feel like an archival cognitive workspace?
7. Does it respect the Activity / Evidence distinction?
8. If evidence exists, can the user sense it before expanding?
