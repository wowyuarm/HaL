# HaL Web Design Tokens

Status: Active
Layer: L3 visual foundations

This file owns the canonical visual foundations for HaL Web. It captures reusable tokens and their usage constraints without drifting into page-specific IA or component anatomy.

## Scope

Owns:
- color tokens and semantic aliases
- typography scale and font rules
- spacing scale and density presets
- depth, radius, and motion primitives

Does not own:
- page-specific layout behavior
- component anatomy
- state placement rules beyond token availability
- event-to-surface mapping

## 1. Color system

HaL uses two layers: **functional foundation** and **semantic aliases**.

The split covers reusable color and structural semantics. Add new semantic tokens only when a pattern is clearly reused across multiple surfaces.

### 1.1 Foundation tokens

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

  /* Borders */
  --border-strong: rgba(36, 33, 29, 0.18);
  --border-default: rgba(36, 33, 29, 0.14);
  --border-subtle: rgba(36, 33, 29, 0.09);

  /* Semantic borders */
  --border-accent: rgba(74, 122, 116, 0.34);
  --border-human: rgba(154, 120, 64, 0.28);
  --border-danger: rgba(162, 82, 72, 0.28);
  --border-success: rgba(90, 138, 106, 0.28);
  --border-warning: rgba(184, 134, 59, 0.3);
}
```

### 1.2 Semantic alias tokens

```css
:root {
  --hal-canvas: var(--surface-base);
  --hal-panel: var(--surface-raised);
  --hal-paper: var(--surface-paper);
  --hal-veil: var(--surface-veil);
  --hal-float: var(--surface-elevated);
  --hal-inset: var(--surface-inset);

  --hal-text: var(--text-primary);
  --hal-text-muted: var(--text-secondary);

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

  --hal-divider: var(--border-default);
  --hal-divider-subtle: var(--border-subtle);
  --hal-focus-ring: rgba(74, 122, 116, 0.22);
  --hal-hover: var(--surface-hover);
  --hal-selection: rgba(74, 122, 116, 0.18);
  --hal-evidence-seam: rgba(74, 122, 116, 0.34);
}
```

### 1.3 Color rules

- HaL output uses `--hal-text` by default. No dedicated AI color.
- Human contributions use `--hal-human` as a marker, never a large fill.
- Live and connected states use `--hal-live`.
- State colors should appear first as compact markers, then escalate only if needed.
- Large fields remain neutral and paper-like.
- Avoid bright blue, neon green, or generic dashboard status palettes.

## 2. Typography

### 2.1 Font families

```css
:root {
  --font-sans: "IBM Plex Sans", "Noto Sans SC UI", "Segoe UI", sans-serif;
  --font-serif: "IBM Plex Sans", "Noto Sans SC UI", "Segoe UI", sans-serif;
  --font-mono:
    "Maple Mono Latin", "Noto Sans SC UI", "Maple Mono", "IBM Plex Mono",
    "SFMono-Regular", Menlo, Monaco, Consolas, monospace;
}
```

### 2.2 Font rules

- Sans is the base for UI text, headings, and prose.
- Chinese text uses `Noto Sans SC` for a neutral, readable base that mixes cleanly with the Latin stack.
- Monospace is sparse and functional. Default scope: code, event-facing technical text, file paths, IDs, and other compact operational text where alignment or technical tone matters.
- Markdown headings inside the Working Log should read as restrained section markers, not page-level display titles.

### 2.3 Type scale

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

| Role | Size | Weight | Line height | Use |
| --- | --- | --- | --- | --- |
| `title` | 23px | 600 | 30px | Primary page heading, thread detail title |
| `heading` | 17px | 600 | 23px | Session title, section headers |
| `subheading` | 15px | 600 | 21px | Small section headers, empty-state titles |
| `body` | 15px | 400 | 24px | Default UI text |
| `reading` | 16px | 400 | 27px | Main prose surfaces, BRIEF, long-form reading |
| `meta` | 12.5px | 500 | 18px | State labels, compact metadata |
| `caption` | 11.5px | 500 | 16px | Tool rows, evidence labels, technical chrome |

### 2.4 Type rules

- Default UI body size is 15px.
- Use weight and spacing for emphasis before reaching for color.
- Main reading surfaces use `reading` scale rather than `body`.
- BRIEF prose and assistant prose share the same base reading rhythm; BRIEF may step up heading size, not body density.

## 3. Spacing and density

HaL uses Tailwind's 4px base scale.

### 3.1 Spacing by hierarchy level

| Level | Internal spacing | Gap between siblings |
| --- | --- | --- |
| Event | 4–8px | 4px |
| Turn | 12–16px | 8–12px |
| Session group | 16–20px | 16–20px |
| Thread / page | 24–32px | 24–32px |

### 3.2 Density rules

- Density tracks hierarchy: event items are tighter than turn containers.
- Working Log may be one spacing step tighter than BRIEF content.
- Bordered paper objects should feel close to their content.
- For bordered message and code surfaces, left inset and top inset should feel roughly equivalent unless a dedicated seam or action needs extra room.

### 3.3 Shared density presets

- `compact` — system and tool rows
- `comfortable` — human-bounded paper objects and composer shell
- `spacious` — empty-state notes
- `roomy` — larger paper panels

## 4. Depth

Depth is expressed through **surface contrast and borders**. Shadow is rare.

### 4.1 Surface mapping

| Surface | Color | Use |
| --- | --- | --- |
| `base` | `#F7F4EF` | Main canvas, page field |
| `raised` | `#EFECE6` | Grouped containers, navigation items |
| `elevated` | `#FFFFFF` | Popovers, menus, floating review surfaces |
| `inset` | `#E8E4DD` | Composer textarea, code blocks, evidence wells |
| `paper` | `rgba(255, 255, 255, 0.72)` | Translucent overlay on cards and containers |
| `veil` | `rgba(255, 252, 247, 0.58)` | Sidebar backdrop |
| `hover` | `rgba(36, 33, 29, 0.06)` | Inline hover micro-step |

### 4.2 Border rules

- `--border-subtle` — separators and hairline dividers
- `--border-default` — standard object boundaries
- `--border-strong` — active or expanded emphasis
- All borders are 1px solid rgba.

### 4.3 Shadow tokens

```css
:root {
  --shadow-sm: 0 1px 2px rgba(36, 33, 29, 0.06);
  --shadow-popover: 0 6px 18px rgba(36, 33, 29, 0.1);
}
```

- Default components use no shadow.
- `--shadow-sm` is reserved for scroll-attached objects that must read as slightly lifted.
- `--shadow-popover` is reserved for truly floating UI.

## 5. Radius

```css
:root {
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
}
```

| Token | Use |
| --- | --- |
| 4px | badges, tags, compact buttons, evidence fragments |
| 8px | cards, list items, inputs |
| 12px | popovers, dialogs, floating review surfaces |

Composer may intentionally exceed the shared radius when treated as the primary writing object of the page. That exception should stay limited to the outer composer shell.

## 6. Motion

```css
:root {
  --duration-fast: 100ms;
  --duration-normal: 180ms;
  --duration-slow: 300ms;
  --ease-standard: ease-out;
}
```

### Motion rules

- **Fast**: hover, focus, press, small state shifts
- **Normal**: expand/collapse, panel reveal, inline status changes
- **Slow**: major layout transitions
- Motion is opacity- and translate-driven. No spring, bounce, or decorative animation.
- A subtle pulse on live-state indicators is acceptable.

## 7. Change policy

- Token intent changes are low frequency.
- Numeric values and usage constraints are medium frequency.
- New semantic tokens should be added only when reuse is real, not speculative.

## 8. Pending normalization questions

- Whether `meta` and `caption` should stay fractional or be normalized to integer px values
- Final allowed scope of monospace beyond code, paths, IDs, and event-facing technical text
