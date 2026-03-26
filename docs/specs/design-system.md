# HaL Design System

**Date:** 2026-03-15
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

| Quality            | Meaning                                                                  |
| ------------------ | ------------------------------------------------------------------------ |
| **Restrained**     | Visual budget goes to content, not decoration                            |
| **Transparent**    | All activity has evidence, is traceable and reviewable                   |
| **Structured**     | Visual hierarchy mirrors cognitive hierarchy; the antithesis of entropy  |
| **Human-directed** | The human is always the source of intent; HaL is the medium of execution |

---

## 2. Visual World

HaL's visual world is a **quiet archival worktable**.

Not a futuristic command center. Not a playful productivity app. A table covered
with paper, graphite marks, metal clips, marginal notes, and durable records.
Surfaces feel mineral, papered, and slightly tactile. Emphasis comes from
structure and evidence, not decoration.

Color roles in this world:

| Physical source       | Design role                           |
| --------------------- | ------------------------------------- |
| Warm paper, vellum    | Base surfaces                         |
| Graphite, dust        | Structural edges and borders          |
| Oxidized teal metal   | Live system state, interaction accent |
| Brass annotation tabs | Human authorship markers              |
| Amber oxide           | Warning, attention needed             |
| Iron red              | Danger, failure, destructive action   |
| Moss, completion ink  | Success, brief completed              |

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

---

## 4. Layout

Two-region layout: a collapsible navigation panel and a main content area.
On desktop, turn-level process detail may open as an embedded right rail that
compresses the working log instead of floating above it. BRIEF and episode
preview may still use right-edge sheets when they are treated as standalone
reading objects.

Surface rules:

- Layout regions separate by spacing, width, and a hairline border — not
  contrasting background color
- The navigation panel uses `--surface-veil` for glass-like depth on the
  shared base surface
- Composer is present only for interactive sessions — absent otherwise
- When the composer is treated as a detached writing object, it should sit in
  its own bottom breathing room rather than feeling boxed into the scrolling
  message field

---

## 5. Color System

Two layers: **functional foundation** and **HaL semantic aliases**.

The two-layer split currently covers color and structural semantics. Component-
level semantic tokens (e.g., `--hal-turn-surface`, `--hal-brief-gap`) should be
added only when a pattern is clearly reused across multiple surfaces.

### 5.1 Foundation Tokens

```css
:root {
  color-scheme: light;

  /* Surfaces */
  --surface-base: #f7f4ef;
  --surface-raised: #efece6;
  --surface-elevated: #ffffff;
  --surface-inset: #e8e4dd;
  --surface-paper: rgba(255, 255, 255, 0.72);
  --surface-veil: rgba(255, 252, 247, 0.58);
  --surface-hover: rgba(36, 33, 29, 0.06);

  /* Text */
  --text-primary: #24211d;
  --text-secondary: #7a756d;
  --text-on-accent: #ffffff;

  /* Accent and semantic hues */
  --color-accent: #4a7a74;
  --color-accent-subtle: #e8f0ef;
  --color-human: #9a7840;
  --color-human-subtle: #f5ede0;
  --color-danger: #a25248;
  --color-danger-subtle: #faeae8;
  --color-success: #5a8a6a;
  --color-success-subtle: #ecf3ed;
  --color-warning: #b8863b;
  --color-warning-subtle: #f7efe1;

  /* Borders — rgba-based for natural blending across surfaces */
  --border-strong: rgba(36, 33, 29, 0.18);
  --border-default: rgba(36, 33, 29, 0.14);
  --border-subtle: rgba(36, 33, 29, 0.09);

  /* Semantic borders — derived from hue at lower opacity */
  --border-accent: rgba(74, 122, 116, 0.34);
  --border-human: rgba(154, 120, 64, 0.28);
  --border-danger: rgba(162, 82, 72, 0.28);
  --border-success: rgba(90, 138, 106, 0.28);
  --border-warning: rgba(184, 134, 59, 0.3);
}
```

### 5.2 Semantic Alias Tokens

```css
:root {
  /* Workspace surfaces */
  --hal-canvas: var(--surface-base);
  --hal-panel: var(--surface-raised);
  --hal-paper: var(--surface-paper);
  --hal-veil: var(--surface-veil);
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
  --hal-hover: var(--surface-hover);
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
  --font-sans: "IBM Plex Sans", "Noto Sans SC UI", "Segoe UI", sans-serif;
  --font-serif: "IBM Plex Sans", "Noto Sans SC UI", "Segoe UI", sans-serif;
  --font-mono:
    "Maple Mono Latin", "Noto Sans SC UI", "Maple Mono", "IBM Plex Mono",
    "SFMono-Regular", Menlo, Monaco, Consolas, monospace;
}
```

Latin letters, digits, and common Western punctuation are self-hosted with
`Maple Mono` for tool-layer text: code, timestamps, IDs, tags, buttons, and
other compact operational labels. Body copy and headings share the same sans
base to avoid cross-script clashes.
Chinese text uses `Noto Sans SC` for a neutral, readable base that mixes cleanly
with Maple Mono.
Markdown headings inside conversation flow should read as restrained section
markers, not page-level display titles. Keep conversation `h1/h2/h3` close
enough in scale that long assistant answers do not fragment into oversized
hero blocks.

### 6.2 Type Scale

```css
:root {
  --type-title-size: 23px;
  --type-title-line: 30px;
  --type-title-weight: 600;

  --type-heading-size: 17px;
  --type-heading-line: 23px;
  --type-heading-weight: 600;

  --type-subheading-size: 15px;
  --type-subheading-line: 21px;
  --type-subheading-weight: 600;

  --type-body-size: 15px;
  --type-body-line: 24px;
  --type-body-weight: 400;

  --type-reading-size: 16px;
  --type-reading-line: 27px;
  --type-reading-weight: 400;

  --type-meta-size: 12.5px;
  --type-meta-line: 18px;
  --type-meta-weight: 500;

  --type-caption-size: 11.5px;
  --type-caption-line: 16px;
  --type-caption-weight: 500;
}
```

| Role           | Size   | Weight | Line Height | Use                                                  |
| -------------- | ------ | ------ | ----------- | ---------------------------------------------------- |
| **title**      | 23px   | 600    | 30px        | Primary page heading, thread detail title            |
| **heading**    | 17px   | 600    | 23px        | Session title, section headers                       |
| **subheading** | 15px   | 600    | 21px        | Small section headers, empty-state titles            |
| **body**       | 15px   | 400    | 24px        | Default UI text, thread descriptions                 |
| **reading**    | 16px   | 400    | 27px        | Main assistant prose, BRIEF prose, long-form reading |
| **meta**       | 12.5px | 500    | 18px        | State labels, session metadata, compact annotations  |
| **caption**    | 11.5px | 500    | 16px        | Tool rows, evidence labels, technical chrome         |

### 6.3 Type Rules

- Default UI body size is 15px.
- Use weight and spacing for emphasis before reaching for color.
- Monospace is sparse and functional — code, event payloads, file paths only.
- Main reading surfaces use `reading` scale rather than `body`.
- BRIEF prose and assistant prose share the same base reading rhythm; BRIEF may step up heading size, not body density.

---

## 7. Spacing

Uses Tailwind's 4px base scale (`p-1` = 4px, `p-2` = 8px, etc.).

### 7.1 Spacing by Hierarchy Level

| Level         | Internal spacing | Gap between siblings |
| ------------- | ---------------- | -------------------- |
| Event         | 4–8px            | 4px                  |
| Turn          | 12–16px          | 8–12px               |
| Session group | 16–20px          | 16–20px              |
| Thread / page | 24–32px          | 24–32px              |

### 7.2 Density Rules

- Default density supports long working sessions without fatigue.
- Density tracks hierarchy: event items tighter than turn containers.
- Working log may be one spacing step tighter than BRIEF content.
- Bordered paper objects should feel close to their content. Horizontal padding is typically tighter than early mockups suggested.
- For bordered message and code surfaces, left inset and top inset should feel roughly equivalent unless a dedicated seam or button needs extra room.
- Current shared density presets are:
  `compact` for system/tool rows,
  `comfortable` for user bubbles and composer shell,
  `spacious` for empty-state notes,
  `roomy` for larger paper panels.

### 7.3 Layout Width Rules

- Session working log and thread detail share a narrow reading column. Current shared default is `49rem`, with smaller effective width coming from viewport padding on narrower screens.
- The session header may span the full row so navigation and view toggles do not make the page feel under-filled.
- Outer page padding may grow before the main reading column grows. Prefer more canvas around content over a wider text block.

---

## 8. Depth

Depth is expressed through **surface contrast and borders**. Shadow is rare.

### 8.1 Surface Mapping

| Surface    | Color                       | Use                                            |
| ---------- | --------------------------- | ---------------------------------------------- |
| `base`     | `#F7F4EF`                   | Main canvas, page field                        |
| `raised`   | `#EFECE6`                   | Grouped containers, navigation items           |
| `elevated` | `#FFFFFF`                   | Popovers, floating BRIEF panel, menus          |
| `inset`    | `#E8E4DD`                   | Composer textarea, code blocks, evidence wells |
| `paper`    | `rgba(255, 255, 255, 0.72)` | Translucent overlay on cards and containers    |
| `veil`     | `rgba(255, 252, 247, 0.58)` | Subtle frosted glass for sidebar backdrop      |
| `hover`    | `rgba(36, 33, 29, 0.06)`    | Inline hover micro-step for rows and controls  |

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
  --shadow-popover: 0 6px 18px rgba(36, 33, 29, 0.1);
}
```

- Default components: **no shadow**
- Scroll-anchored elements use `--shadow-sm` when they stay visually attached to
  the scrolling surface
- Detached floating writing objects may use `--shadow-popover`
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

| Token | Use                                               |
| ----- | ------------------------------------------------- |
| 4px   | Badges, tags, compact buttons, evidence fragments |
| 8px   | Cards, turn containers, list items, inputs        |
| 12px  | Popovers, floating BRIEF, dialogs                 |

Composer may intentionally exceed the shared radius when it is treated as the
primary writing object of the page. That exception should stay limited to the
outer composer shell, not spread to ordinary cards or message containers.

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

| State                     | Token           | Use                                                  |
| ------------------------- | --------------- | ---------------------------------------------------- |
| Live / active / connected | `--hal-live`    | Session active, WebSocket connected, turn processing |
| Success / completed       | `--hal-success` | Brief completed, tool succeeded                      |
| Warning / attention       | `--hal-warning` | Slow response, needs review                          |
| Danger / failed           | `--hal-danger`  | Turn failed, destructive action                      |
| Human-authored            | `--hal-human`   | Human contribution marker                            |

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

### 12.1 Evidence Indicator

HaL's signature design element is the **evidence indicator** — a compact
visual marker on messages or turns that signals underlying process detail is
available for inspection.

The indicator should be quiet at rest but clearly actionable. On
interaction, it opens the turn's process view. It should read like a seam in
the page, not like a generic button.

```css
:root {
  --hal-evidence-seam: rgba(74, 122, 116, 0.34);
}
```

Evidence indicators are structural signifiers, not decorative. They answer:
"Is there process detail here if I want to inspect it?"

When a turn contains only a direct reply with little observable work, the seam
should recede further than a tool-heavy turn. Significance affects weight.

### 12.2 BRIEF as Compiled Context

BRIEF is not a generic detail drawer. It is a compiled working artifact:

- Feels authored and durable, not generated.
- Uses elevated or raised surface.
- Maintains strong typographic readability (`text-reading`) at lower
  density than the message flow.

### 12.3 Working Log Message Grammar

- Assistant turns are part of the page flow, not speaker bubbles.
- Human turns may use a light bounded paper container, but the human marker should come from seam or border tint first, not a large colored fill.
- Message-local timestamps are optional and should not be shown by default if they compete with reading flow.
- Tool results and system notices are secondary rows. They use `caption` or `meta` scale and must not compete with the main prose layer.
- Evidence affordances remain the one explicit bounded object attached to an assistant turn, but they should stay lighter than action buttons or cards.

---

## 13. Information Architecture: Activity + Evidence

Session content separates into two tiers. This is a **principle**, not a
specific UI pattern — implementations may vary.

### 13.1 Activity (Primary View)

What the user needs for scanning and momentum:

- Human prompts and direction
- HaL responses and key outputs
- A light process seam attached to assistant turns
- Tool result summaries translated into human-readable actions
- State markers and failure summaries

System internals (`context.compiled`, `loop.iteration`) are **not shown**
in the activity view.

### 13.2 Evidence (On-Demand)

Diagnostic detail available through explicit user action:

- Step-grouped process timeline
- Inserted notes, returned subtask results, and carried-in context
- Full event list in original order
- Tool inputs and outputs
- Execution traces and diagnostics
- Uses inset surfaces and monospace text only in the deepest layer

Default process detail should prefer collaboration objects over runtime counters.
Show mounted or pulled-in threads before internal message-window counts.

### 13.3 Rules

- Process detail is entered through explicit interaction, never auto-expanded.
- The default seam should convey that work happened without turning into a loud summary chip.
- Process detail should not interrupt the main reading flow; on desktop it may compress the working column into a three-region workspace.
- BRIEF, episode preview, and turn process detail remain mutually exclusive. Only one review object should be open at a time.
- Turn process detail headers should not stack multiple lines that all repeat the same count in different words.
- Step headings should be action-first. If rationale is shown, it belongs on the quieter secondary line.
- A step unit should keep a call's tool actions and their concise return results together.
- Concrete tool-action labels should live in one stable visual slot. A single tool item may collapse spacing, but it should not switch to a different typographic role than the same item would use inside a longer list.
- Step units and inserted notes should share one timeline skeleton; distinguish them by wording and depth before reaching for alternate borders or colors.
- Scope rows should prefer mounted and pulled-in threads. Internal insert counts belong deeper in raw evidence, not in the default rail summary.
- Inserted or external notes should read like tagged interruptions, not full system-narration sentences.
- Order carries more value than exact clock time in turn process detail; timestamps stay out of the default rail.

### 13.4 Session and Thread Overview Hierarchy

- Thread detail and session pages should use the same core content width.
- In thread detail, thread name is a true page title, not body-sized metadata.
- Session lists use a primary line plus secondary metadata line. Do not place timestamp, status, and counts all at the same visual weight.
- In grouped session lists, lifecycle status belongs to the group header. Do not repeat per-session status badges inside each row.
- Thread-detail session lists may group runs by lifecycle state. These groups should read like light ledger sections, not stacked accordion cards.
- Group toggles use compact chevron disclosure, `meta`-scale labels, and restrained count markers. Use border and spacing before fill.
- Collapse/expand motion should stay subtle: quick opacity and height changes only, with no bounce or theatrical slide.
- Session-row actions appear only on hover or focus and should stay at the row end as lightweight contextual controls. Prefer no more than two visible controls at once.
- Session renaming in thread detail should happen inline within the row rather than through a separate dialog, so the list keeps its ledger rhythm.
- Empty states should read like calm paper notes, not dashed placeholders or form errors.

---

## 14. Control Grammar

Components feel like objects on an archival worktable — paper cards, clipped
ledger headers, inset record wells — not generic SaaS widgets.

### 14.1 Control Families

#### Contextual Controls

Controls subordinate to content: navigation toggles, inline actions, sheet
close buttons, icon buttons.

- Rest: transparent background, `--hal-text-muted`, optional hairline border
  (`--border-subtle`)
- Hover: text promotes to `--hal-text`, border promotes to `--border-default`.
  **No background change.**
- These controls are furniture — present and reachable, never attention-seeking.
- In overflow menus, semantic escalation should usually happen through text color only. For example, a supportive action may use accent text and a destructive action may use danger text, without adding filled backgrounds.

#### Primary Action

`--color-accent` fill, `--text-on-accent` text. **No shadow.** Maximum one per
visible context. Reserved for the single most important action in scope.

#### Secondary Action

Bordered, `--surface-paper` fill. Clearly bounded as a button without being
loud. Appropriate for Cancel, Scope, and similar supporting actions. When a
view toggle sits beside a primary action in a button group, secondary is
acceptable for visual cohesion.

#### Destructive Ghost

Transparent at rest (same as contextual). Hover reveals `--color-danger` accent
— color escalation is the warning signal.

### 14.2 Selectable Rows

Thread rows, session rows, and dialog choice rows share a common interaction
grammar:

| State    | Background                      | Text    | Marker                |
| -------- | ------------------------------- | ------- | --------------------- |
| Rest     | transparent                     | muted   | —                     |
| Hover    | `--surface-hover` (micro-step)  | primary | —                     |
| Selected | `--hal-selection` (accent tint) | primary | left accent seam 2 px |

Rules:

- Hover and selected **must** be visually distinguishable.
- Hover is lighter than selected — transient suggestion, not commitment.
- `--surface-elevated` / `--hal-float` is **not** appropriate for hover or
  selected backgrounds — reserved for floating UI.

### 14.3 Interactive Surface Hierarchy

For inline interactive elements (rows, list items, toggles):

1. Rest — inherits parent surface (transparent)
2. Hover — one micro-step above parent via `--surface-hover`
3. Selected — one clear step with accent tint via `--hal-selection`

`--surface-elevated` is reserved for floating UI (popovers, menus, sheets).
It must not appear as a hover or selected surface for inline elements.

### 14.4 Shadow Rules

| Object                                  | Shadow             | Rationale                          |
| --------------------------------------- | ------------------ | ---------------------------------- |
| Buttons (any variant)                   | none               | Fill and border are sufficient     |
| Inline rows and cards                   | none               | Border is the primary depth device |
| Scroll-anchored elements (composer)     | `--shadow-sm`      | Sits above scrolling content       |
| Floating UI (popovers, dialogs, sheets) | `--shadow-popover` | True floating layer                |

Shadow on `--surface-base` or `--surface-raised` without a floating context
is a design error.

### 14.5 Do / Don't

**Do:**

- Use transparent backgrounds for controls subordinate to content
- Express hover through text/border promotion before reaching for background
- Keep exactly one primary (accent fill) button per visible scope
- Use left-border accent seam as the signature for selected state
- Reserve shadow for truly floating elements

**Don't:**

- Use `--surface-elevated` / `--hal-float` as a hover or selected surface
- Add shadow to buttons — fill color is the signal
- Make hover visually heavier than selected
- Use identical visual treatment for hover and selected on the same element
- Apply `--shadow-popover` to non-floating elements

### 14.6 Composer Attachment Grammar

Composer attachments are part of the same writing surface, not a detached upload bar.

- Attachment previews sit **inside** the composer shell, above the text row.
- Attachment and send controls stay on a dedicated action row, aligned to the same horizontal inset as the writing area.
- Default preview grammar is compact and low-noise: keep the file name and format, and avoid extra type badges or nested preview cards.
- Thumbnails are optional, not the default. Only use them when visual recognition is genuinely important.
- Composer and user-message attachments should share the same compact grammar. The composer version may expose remove controls; the message version should not.
- Avoid nested bordered objects inside the composer shell unless a specific attachment workflow truly needs another level of containment.
- On narrow screens, previews wrap before the text row grows taller than necessary.

### 14.7 Markdown and Embedded Content

Markdown is not a browser default and not a generic `prose` dump. It is a first-class reading surface.

- Use a shared markdown renderer component so assistant messages, user messages, and BRIEF do not drift.
- Clear first-child and last-child margins inside bounded containers so markdown does not silently reintroduce excess padding.
- Inline code should read like an in-sentence annotation: subtle surface, warm text emphasis, no decorative pill styling.
- Code blocks use a restrained inset surface, no shadow, and no persistent toolbar chrome. Copy affordance may appear on hover only.
- Tables are reading objects, not cards: full available width, horizontal rules only, no outer box, no hover theatrics.
- External links open in a new tab and should use understated underline treatment rather than button-like styling.
- Internal thread-episode links inside BRIEF or episode markdown should stay in-app and open the shared review panel rather than spawning a browser tab.

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
