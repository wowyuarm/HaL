# HaL Web State and Event Spec

Status: Active
Layer: L5 state semantics and event rendering

This file defines how product and runtime states map to visual expression, copy, placement, and event rendering across HaL Web.

## Scope

Owns:
- canonical state names
- state meaning
- expression order and escalation
- placement guidance by object type
- canonical event-category -> surface mapping rules
- transformation rules from runtime detail into readable activity summaries
- Process detail structuring rules that belong to evidence rendering rather than page layout
- suppression rules for internal noise in the primary flow

Does not own:
- raw token definitions
- domain lifecycle rules themselves
- page layout
- low-level component styling
- domain model definitions

## 1. Canonical states

- `live`
- `success`
- `warning`
- `danger`
- `human-authored`
- `neutral` / `muted`

## 2. State semantics

| State | Token | Meaning |
| --- | --- | --- |
| live | `--hal-live` | active, connected, or currently processing |
| success | `--hal-success` | completed successfully |
| warning | `--hal-warning` | attention needed, degraded, or review-worthy |
| danger | `--hal-danger` | failed or destructive |
| human-authored | `--hal-human` | human contribution marker |
| neutral / muted | n/a | background or secondary state without semantic escalation |

## 3. Expression order

Prefer earlier forms; escalate only when needed:

1. dot or seam color
2. inline text label
3. badge
4. border tint
5. subtle background fill
6. banner

## 4. Visibility rules

- Active turns should show live state.
- Completed units should show completion state without requiring expansion.
- Review surfaces may preserve evidence of prior state while reducing live accents.
- Human ownership should be visible where authorship matters, not on every line.

## 5. Initial matrix

| State | Preferred label style | Default expression | Escalation path | Notes |
| --- | --- | --- | --- | --- |
| live | short, calm, present-tense | dot or inline label | dot -> label -> badge | prefer `live` or `connected`, avoid mixed phrasing |
| success | compact completion label | inline label or badge | label -> badge -> border | do not over-celebrate |
| warning | concise attention cue | inline label | label -> badge -> border -> fill | reserve for true review need |
| danger | direct failure or destructive wording | inline label or badge | label -> badge -> border -> fill -> banner | use strongest contrast carefully |
| human-authored | actor marker, not a status sentence | seam or subtle tint | seam -> label -> border | should not compete with failure/live states |
| neutral/muted | no semantic label by default | text tone only | text -> divider -> subtle structure | default resting state |

## 6. Event rendering contract

New or renamed runtime event types must still map into one of these categories. This file owns the stable category-level contract for how events become readable UI.

### 6.1 Surface tiers

1. **Working Log** — primary readable collaboration flow
2. **Process detail** — structured inspection layer for a turn
3. **Raw events** — deepest original event layer

### 6.2 Mapping rules

- The Working Log favors readable collaboration objects over raw runtime counters.
- Process detail groups step-level work into coherent action-first units.
- Tool results stay attached to the tool action that produced them.
- Inserted or carried-in context should read like concise tagged interruptions, not full runtime narration.
- Relevant thread context belongs earlier than internal counters or diagnostics.
- Raw events preserve original event order and structure.
- In default Process detail, order carries more value than exact clock time; timestamps stay out unless the task specifically demands them.

### 6.3 Event-category mapping

| Event category | Working Log treatment | Process detail treatment | Raw events treatment | Notes |
| --- | --- | --- | --- | --- |
| human input | show as a first-class turn in the reading flow | include only if needed for turn context | preserve original event payload | primary collaboration object |
| assistant output | show as a first-class turn in the reading flow | include related steps and inserted notes around it | preserve original event payload | primary collaboration object |
| tool action | summarize only when it helps explain progress or outcome | group into step-level action units with concise results | preserve original event payload | avoid raw tool chatter in the Working Log |
| tool result | summarize as human-readable outcome | keep attached to the tool action that produced it | preserve original event payload | result belongs with action |
| injected or carried-in context | suppress unless it materially changed the turn | show as inserted note or scope context | preserve original event payload | avoid runtime narration tone |
| lifecycle event | summarize only when it changes what the user should do next | show in Process detail when relevant to the turn or session | preserve original event payload | includes briefing, failure, and completion boundaries |
| failure event | always surface a readable failure summary | show the failed step and nearby context | preserve original event payload | failure is never raw-only |
| attachment event | show with the associated human or assistant turn | include only if it affects process understanding | preserve original event payload | attachment is not its own narrative lane by default |

### 6.4 Open areas to formalize

- a runtime event-type appendix for exact backend event names
- how Process detail should represent parallel subtask clusters
- when a tool action deserves a visible Working Log summary versus staying evidence-only

## 7. Pending questions

- whether socket copy should prefer `live` or `connected`
- whether review `open / resolved` belongs in this matrix or a review-state extension
- which object types need distinct state rows: session, turn, tool action, evidence item, thread row

## Inputs

- `../thread-system.md`
- `../message-injects.md`
- `../workspace-layout.md`
- `../design-system.md`
- `glossary.md`
