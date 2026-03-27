# HaL Web Surface Spec

Status: Active
Layer: L2 surface information architecture

This file owns page- and surface-level rules that are too specific for `../design-system.md` but broader than a single component.

## Scope

Owns:
- surface hierarchy and reading flow
- what belongs to the primary view versus inspection layers
- thread detail / session page / review-surface behavior
- auxiliary surface relationships among BRIEF, episode preview, and Process detail
- page-level reading width and region behavior

Does not own:
- raw token values
- low-level component variants
- domain truth for thread/session/turn/event
- event-row microcopy or step formatting rules

## 1. Surface model

### 1.1 Primary surfaces

- **Thread detail** — thread-level continuity and session entry surface
- **Session page** — active collaboration surface containing the Working Log
- **Working Log** — primary readable session flow

### 1.2 Review surfaces

- **BRIEF** — thread-level compiled context surface
- **Episode preview** — focused reading surface for an immutable episode artifact
- **Process detail** — turn-level structured evidence surface
- **Raw events** — deepest event-level inspection layer inside Process detail

## 2. Layout doctrine at surface level

- The base workspace is navigation plus primary content.
- On desktop, Process detail may open as an embedded right rail that compresses the Working Log instead of floating above it.
- BRIEF and episode preview may use right-edge reading sheets when they are treated as standalone reading objects.
- Layout regions separate through spacing, width, and hairline borders rather than heavy surface contrast.
- When the composer is treated as a detached writing object, it should sit in its own bottom breathing room rather than feeling boxed into the scrolling field.

## 3. Reading width

- Thread detail and session pages share the same narrow reading measure.
- Current shared default is `49rem`, with smaller effective width coming from viewport padding on narrower screens.
- Outer page padding should grow before the main reading column grows.
- The session header may span wider than the reading column so navigation and mode controls do not make the page feel under-filled.

## 4. Activity and Evidence

Session content separates into a readable primary flow and on-demand inspection layers.

### 4.1 Working Log as primary activity flow

The Working Log should optimize for scanning and momentum.

It includes:
- human prompts and direction
- HaL responses and key outputs
- light process seams attached to turns when inspectable work exists
- tool-result summaries translated into human-readable actions
- state markers and failure summaries

It excludes:
- raw runtime counters
- low-level diagnostic payloads
- implementation events that do not help the reader understand what happened

### 4.2 Evidence as on-demand inspection

Evidence is entered explicitly, never auto-expanded into the main flow.

The default evidence path is:
1. **Process detail** — structured first inspection layer for a turn
2. **Raw events** — original event-level records in order

Relevant thread context is more useful than raw runtime counters in the default inspection layer.

## 5. Review-surface coordination

- Process detail is entered through explicit interaction.
- Process detail should not interrupt the main reading flow; on desktop it may compress the working column into a three-region workspace.
- Only one review surface should dominate attention at a time.
- BRIEF, episode preview, and turn-level Process detail should not compete simultaneously as equal primary panels.
- Surface naming should reflect the user task, not the implementation container.

## 6. Session and thread overview hierarchy

- In thread detail, the thread name is a true page title, not body-sized metadata.
- Session lists use a primary line plus a secondary metadata line. Timestamp, status, and counts should not all sit at the same visual weight.
- In grouped session lists, lifecycle status belongs to the group header rather than repeating as loud per-row badges.
- Thread-detail session groups should read like light ledger sections, not stacked accordion cards.
- Group toggles use compact disclosure, `meta`-scale labels, and restrained count markers.
- Collapse and expand motion stays subtle.
- Session renaming should happen inline within the row so the list keeps its ledger rhythm.
- Empty states should read like calm paper notes, not placeholders or error shells.

## 7. Frozen decisions

- The thread-level compiled review surface is **BRIEF**, not a vague generic `Thread` surface.
- `Thread` is not a canonical label for a control that opens BRIEF.
- `Process detail` is the canonical first evidence layer; `process rail` is only one presentation mode.

## 8. Remaining design questions

- whether Process detail should keep the right-rail layout as the default desktop presentation or formalize multiple canonical modes
- how far the BRIEF reading surface should expand beyond the BRIEF artifact itself if related thread context is later surfaced there
