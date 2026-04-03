import { bySeq, getFiniteNumber, getString, getStringArray } from '@/lib/event-helpers'
import type { SessionEvent } from '@/lib/types'

export type ProcessTone = 'live' | 'success' | 'warning' | 'danger' | 'muted' | 'human-authored'
export type ProcessEntryStatus = 'running' | 'completed' | 'failed'
export type ProcessCountKey =
  | 'search'
  | 'fetch'
  | 'recall'
  | 'read'
  | 'edit'
  | 'command'
  | 'subtask'

type ProcessCounts = Record<ProcessCountKey, number>

const PROCESS_COUNT_ORDER: ProcessCountKey[] = [
  'search',
  'fetch',
  'recall',
  'read',
  'edit',
  'command',
  'subtask',
]

export interface ProcessPreview {
  summaryText: string
  hintText: string | null
  countSummaryText: string | null
  liveText: string | null
  countText: string
  tone: ProcessTone
  hasHumanIntervention: boolean
  stepCount: number
  noteCount: number
  totalRecords: number
}

export interface ProcessToolItem {
  id: string
  toolName: string
  label: string
  detail: string | null
  result: string | null
  status: ProcessEntryStatus
}

export interface ProcessStep {
  id: string
  title: string
  summary: string
  status: ProcessEntryStatus
  items: ProcessToolItem[]
  rawEventSeqs: number[]
}

export interface ProcessNote {
  id: string
  label: string
  detail: string | null
  items?: string[]
  tone: ProcessTone
  rawEventSeqs: number[]
}

export type ProcessEntry = { kind: 'step'; step: ProcessStep } | { kind: 'note'; note: ProcessNote }

export interface TurnProcessView {
  entries: ProcessEntry[]
  rawEvents: SessionEvent[]
  preview: ProcessPreview
}

type TurnState = 'running' | 'completed' | 'failed'

interface PendingSubtaskResult {
  label: string
  status: ProcessEntryStatus
  rawEventSeqs: number[]
}

interface MutableStep {
  id: string
  intent: string | null
  items: Map<string, ProcessToolItem>
  // Some completed events omit tool_call_id, so keep a stable fallback queue per tool signature.
  itemIdsByBaseKey: Map<string, string[]>
  rawEventSeqs: number[]
}

export function buildTurnProcessView(
  events: SessionEvent[],
  turnState: TurnState,
): TurnProcessView {
  const ordered = [...events].sort(bySeq)
  const entries: ProcessEntry[] = []
  let currentStep: MutableStep | null = null
  let pendingIntent: string | null = null
  let pendingSubtaskResults: PendingSubtaskResult[] = []
  let sawAssistantOutput = false

  const flushCurrentStep = (nextTurnState: TurnState = turnState) => {
    if (!currentStep) return
    entries.push({ kind: 'step', step: finalizeStep(currentStep, nextTurnState) })
    currentStep = null
  }

  const flushPendingSubtaskResults = () => {
    if (pendingSubtaskResults.length === 0) return
    const note = buildGroupedSubtaskNote(pendingSubtaskResults)
    if (note) entries.push({ kind: 'note', note })
    pendingSubtaskResults = []
  }

  for (const event of ordered) {
    if (!isSubtaskResultEvent(event)) {
      flushPendingSubtaskResults()
    }

    switch (event.type) {
      case 'llm.response_completed':
        if (event.payload.has_tool_calls === true) {
          flushCurrentStep()
          pendingIntent = summarizeAssistantPreview(getString(event.payload, 'content_preview'))
        }
        break

      case 'tool.call_started':
        currentStep = currentStep ?? createStep(event, pendingIntent)
        pendingIntent = null
        addOrUpdateToolItem(currentStep, event, 'running')
        currentStep.rawEventSeqs.push(event.seq)
        break

      case 'tool.call_completed':
        currentStep = currentStep ?? createStep(event, pendingIntent)
        pendingIntent = null
        addOrUpdateToolItem(currentStep, event, 'completed')
        currentStep.rawEventSeqs.push(event.seq)
        break

      case 'tool.call_failed':
        currentStep = currentStep ?? createStep(event, pendingIntent)
        pendingIntent = null
        addOrUpdateToolItem(currentStep, event, 'failed')
        currentStep.rawEventSeqs.push(event.seq)
        break

      case 'assistant.message_completed':
        sawAssistantOutput = true
        flushPendingSubtaskResults()
        if (currentStep) {
          flushCurrentStep()
        } else {
          entries.push({
            kind: 'step',
            step: buildOutputOnlyStep(event, turnState),
          })
        }
        pendingIntent = null
        break

      case 'message.injected':
      case 'subagent.completed':
        if (isSubtaskResultEvent(event)) {
          if (currentStep && mergeSubtaskResultIntoStep(currentStep, event)) {
            currentStep.rawEventSeqs.push(event.seq)
          } else {
            pendingSubtaskResults = appendPendingSubtaskResult(pendingSubtaskResults, event)
          }
          pendingIntent = null
          break
        }
        flushCurrentStep()
        pendingIntent = null
        {
          const note = buildProcessNote(event)
          if (note) entries.push({ kind: 'note', note })
        }
        break

      case 'hook.injected':
        flushCurrentStep()
        pendingIntent = null
        {
          const note = buildProcessNote(event)
          if (note) entries.push({ kind: 'note', note })
        }
        break

      case 'turn.failed':
        flushPendingSubtaskResults()
        if (currentStep) {
          flushCurrentStep('failed')
        } else if (!sawAssistantOutput) {
          entries.push({ kind: 'step', step: buildFailureOnlyStep(event) })
        }
        pendingIntent = null
        break

      default:
        if (currentStep && !isToolEvent(event.type)) {
          flushCurrentStep()
        }
        break
    }
  }

  flushPendingSubtaskResults()
  flushCurrentStep()

  const rawEvents = ordered.filter((event) => isRawProcessEvent(event.type))
  return {
    entries,
    rawEvents,
    preview: buildPreview(entries, rawEvents, turnState),
  }
}

function createStep(event: SessionEvent, intent: string | null): MutableStep {
  return {
    id: `step_${event.seq}`,
    intent,
    items: new Map<string, ProcessToolItem>(),
    itemIdsByBaseKey: new Map<string, string[]>(),
    rawEventSeqs: [],
  }
}

function addOrUpdateToolItem(
  step: MutableStep,
  event: SessionEvent,
  status: ProcessEntryStatus,
): void {
  const toolName = getString(event.payload, 'tool') ?? getString(event.refs, 'tool_name') ?? 'tool'
  const args = readArgs(event.payload)
  const baseKey = buildToolItemBaseKey(toolName, args)
  const key = deriveToolItemKey(step, event, baseKey, status)
  const existing = step.items.get(key)
  const next = existing ?? {
    id: key,
    toolName,
    label: summarizeToolLabel(toolName, args),
    detail: summarizeToolDetail(toolName, args),
    result: null,
    status,
  }

  next.toolName = toolName
  next.label = summarizeToolLabel(toolName, args)
  next.detail = summarizeToolDetail(toolName, args)
  next.status = status

  if (status === 'completed') {
    const shortPreview = compactText(getString(event.payload, 'result_preview'), 96)
    next.result =
      summarizeToolResult(
        toolName,
        args,
        getFiniteNumber(event.payload, 'result_size'),
        getFiniteNumber(event.payload, 'exit_code'),
      ) ?? (allowInlineResultPreview(toolName, args) ? shortPreview : null)
  } else if (status === 'failed') {
    next.result = getString(event.payload, 'error') ?? 'Step failed.'
  }

  step.items.set(key, next)
  syncToolItemQueue(step, baseKey, key, status)
}

function appendPendingSubtaskResult(
  items: PendingSubtaskResult[],
  event: SessionEvent,
): PendingSubtaskResult[] {
  const label = extractSubtaskLabel(event)
  if (!label) return items

  const status = extractSubtaskStatus(event)
  const existing = items.find((item) => sameSubtaskLabel(item.label, label))
  if (existing) {
    existing.status = mergeProcessStatus(existing.status, status)
    existing.rawEventSeqs.push(event.seq)
    return items
  }

  return [
    ...items,
    {
      label,
      status,
      rawEventSeqs: [event.seq],
    },
  ]
}

function deriveToolItemKey(
  step: MutableStep,
  event: SessionEvent,
  baseKey: string,
  status: ProcessEntryStatus,
): string {
  const explicitId = getString(event.refs, 'tool_call_id')
  if (explicitId) return explicitId

  if (status !== 'running') {
    const queued = step.itemIdsByBaseKey.get(baseKey) ?? []
    const runningKey =
      queued.find((candidate) => step.items.get(candidate)?.status === 'running') ?? queued[0]
    if (runningKey) return runningKey
  }

  const existing = step.items.get(baseKey)

  if (existing && existing.status !== 'running' && status === 'running') {
    return `${baseKey}:${event.seq}`
  }

  return existing ? existing.id : baseKey
}

function buildToolItemBaseKey(toolName: string, args: Record<string, unknown> | null): string {
  return `${toolName}:${stableArgSignature(args)}`
}

function syncToolItemQueue(
  step: MutableStep,
  baseKey: string,
  itemId: string,
  status: ProcessEntryStatus,
): void {
  const queue = [...(step.itemIdsByBaseKey.get(baseKey) ?? [])]

  if (status === 'running') {
    if (!queue.includes(itemId)) queue.push(itemId)
  } else {
    const nextQueue = queue.filter((candidate) => candidate !== itemId)
    if (nextQueue.length > 0) {
      step.itemIdsByBaseKey.set(baseKey, nextQueue)
    } else {
      step.itemIdsByBaseKey.delete(baseKey)
    }
    return
  }

  step.itemIdsByBaseKey.set(baseKey, queue)
}

function finalizeStep(step: MutableStep, turnState: TurnState): ProcessStep {
  const items = [...step.items.values()]
  const status = resolveStepStatus(items, turnState)
  return {
    id: step.id,
    title: summarizeStepTitle(items),
    summary: step.intent ?? '',
    status,
    items,
    rawEventSeqs: dedupe(step.rawEventSeqs),
  }
}

function buildOutputOnlyStep(event: SessionEvent, turnState: TurnState): ProcessStep {
  const hasText = Boolean(getString(event.payload, 'content')?.trim())
  return {
    id: `step_${event.seq}`,
    title: hasText ? 'Answer formed' : 'Answer finalized',
    summary: turnState === 'running' ? 'Still shaping the reply.' : 'Final answer prepared.',
    status: turnState === 'failed' ? 'failed' : 'completed',
    items: [],
    rawEventSeqs: [event.seq],
  }
}

function buildFailureOnlyStep(event: SessionEvent): ProcessStep {
  return {
    id: `step_${event.seq}`,
    title: 'Reply stopped on an error',
    summary: summarizeFailureText(getString(event.payload, 'error')),
    status: 'failed',
    items: [],
    rawEventSeqs: [event.seq],
  }
}

function buildProcessNote(event: SessionEvent): ProcessNote | null {
  if (event.type === 'hook.injected') {
    return {
      id: `note_${event.seq}`,
      label: 'note',
      detail: summarizeInjectedNoteDetail(getString(event.payload, 'content')),
      tone: 'muted',
      rawEventSeqs: [event.seq],
    }
  }

  const kind = getString(event.payload, 'kind') ?? 'runtime'

  switch (kind) {
    case 'primary_thread_snapshot':
      return {
        id: `note_${event.seq}`,
        label: 'thread',
        detail: summarizeThreadSnapshotNote(event, 'Primary thread loaded'),
        tone: 'muted',
        rawEventSeqs: [event.seq],
      }
    case 'scope_add_snapshot':
      return {
        id: `note_${event.seq}`,
        label: 'scope',
        detail: summarizeThreadSnapshotNote(event, 'Scope added'),
        tone: 'warning',
        rawEventSeqs: [event.seq],
      }
    case 'turn_context':
      return {
        id: `note_${event.seq}`,
        label: 'context',
        detail: summarizeTurnContextNote(event),
        tone: 'muted',
        rawEventSeqs: [event.seq],
      }
    case 'user_follow_up': {
      const attachments = summarizeFollowUpAttachments(event)
      const detail =
        compactText(getString(event.payload, 'raw_content')) ??
        summarizeAttachmentCount(attachments.length) ??
        compactText(getString(event.payload, 'content'))
      return {
        id: `note_${event.seq}`,
        label: 'input',
        detail,
        items: attachments.length > 0 ? attachments : undefined,
        tone: 'human-authored',
        rawEventSeqs: [event.seq],
      }
    }
    case 'subagent_runtime':
      return null
    case 'context_hint':
      return {
        id: `note_${event.seq}`,
        label: 'context',
        detail: summarizeInjectedNoteDetail(getString(event.payload, 'content')),
        tone: 'muted',
        rawEventSeqs: [event.seq],
      }
    case 'system_reminder':
      return {
        id: `note_${event.seq}`,
        label: 'direction',
        detail: summarizeInjectedNoteDetail(getString(event.payload, 'content')),
        tone: 'warning',
        rawEventSeqs: [event.seq],
      }
    case 'scope_remove':
      return {
        id: `note_${event.seq}`,
        label: 'scope',
        detail: summarizeThreads(getStringArray(event.refs, 'threads')),
        tone: 'warning',
        rawEventSeqs: [event.seq],
      }
    default:
      return {
        id: `note_${event.seq}`,
        label: 'note',
        detail: summarizeInjectedNoteDetail(getString(event.payload, 'content')),
        tone: 'muted',
        rawEventSeqs: [event.seq],
      }
  }
}

function buildGroupedSubtaskNote(items: PendingSubtaskResult[]): ProcessNote | null {
  if (items.length === 0) return null

  const labels = items.map((item) =>
    item.status === 'failed' ? `${item.label} (failed)` : item.label,
  )
  const detail =
    items.length === 1 ? labels[0] : `${formatCount(items.length)} subtasks reported back`

  return {
    id: `note_${items[0]?.rawEventSeqs[0] ?? 'subtasks'}`,
    label: items.length === 1 ? 'subtask' : 'subtasks',
    detail,
    items: items.length > 1 ? labels : undefined,
    tone: items.some((item) => item.status === 'failed') ? 'danger' : 'muted',
    rawEventSeqs: dedupe(items.flatMap((item) => item.rawEventSeqs)),
  }
}

function buildPreview(
  entries: ProcessEntry[],
  rawEvents: SessionEvent[],
  turnState: TurnState,
): ProcessPreview {
  const steps = entries.filter(
    (entry): entry is { kind: 'step'; step: ProcessStep } => entry.kind === 'step',
  )
  const notes = entries.filter(
    (entry): entry is { kind: 'note'; note: ProcessNote } => entry.kind === 'note',
  )
  const entryCount = steps.length + notes.length
  const textOnlyTurn = steps.length === 1 && steps[0]?.step.items.length === 0 && notes.length === 0
  const counts = summarizeProcessCounts(steps)
  const countSummaryText = buildCountSummaryText(counts)
  const directReplyTurn = isDirectReplyTurn(rawEvents, countSummaryText, turnState)
  const hasHumanIntervention =
    turnState === 'running' && notes.some((entry) => entry.note.tone === 'human-authored')

  const summaryText = countSummaryText
    ? countSummaryText
    : directReplyTurn || textOnlyTurn
      ? turnState === 'failed'
        ? 'stopped before settling'
        : 'replied directly'
      : steps.length > 0
        ? `${formatCount(steps.length)} grouped step${steps.length === 1 ? '' : 's'}`
        : notes.length > 0
          ? `${formatCount(notes.length)} note${notes.length === 1 ? '' : 's'}`
          : turnState === 'failed'
            ? 'stopped on an error'
            : 'replied directly'

  return {
    summaryText,
    hintText: buildHintText(steps, notes, turnState),
    countSummaryText,
    liveText: buildHintText(steps, notes, turnState),
    countText: `${formatCount(entryCount)}`,
    tone: turnState === 'failed' ? 'danger' : turnState === 'running' ? 'live' : 'muted',
    hasHumanIntervention,
    stepCount: steps.length,
    noteCount: notes.length,
    totalRecords: rawEvents.length,
  }
}

function isDirectReplyTurn(
  rawEvents: SessionEvent[],
  countSummaryText: string | null,
  turnState: TurnState,
): boolean {
  if (turnState === 'failed') return false
  if (countSummaryText) return false

  const hasAssistantOutput = rawEvents.some((event) => event.type === 'assistant.message_completed')
  const hasToolCall = rawEvents.some(
    (event) =>
      event.type === 'tool.call_started' ||
      event.type === 'tool.call_completed' ||
      event.type === 'tool.call_failed',
  )

  return hasAssistantOutput && !hasToolCall
}

function buildHintText(
  steps: Array<{ kind: 'step'; step: ProcessStep }>,
  notes: Array<{ kind: 'note'; note: ProcessNote }>,
  turnState: TurnState,
): string | null {
  if (turnState === 'failed') return 'Stopped mid-turn.'
  if (turnState !== 'running') return null

  const latestHumanNote = [...notes].reverse().find((entry) => entry.note.tone === 'human-authored')
  const liveStep = [...steps].reverse().find((entry) => entry.step.status === 'running')
  if (
    latestHumanNote &&
    latestEntrySeq(latestHumanNote.note.rawEventSeqs) >= latestStepSeq(liveStep?.step)
  ) {
    return summarizeHumanInterventionHint(latestHumanNote.note.detail)
  }
  if (liveStep) {
    const summarizedIntent = compactText(liveStep.step.summary, 88)
    if (summarizedIntent) return summarizedIntent
    if (!isCountLikeProcessTitle(liveStep.step.title)) return liveStep.step.title
    return null
  }
  if (notes.length > 0) return 'Folding in new information.'
  return 'Still working.'
}

function latestEntrySeq(rawEventSeqs: number[]): number {
  return rawEventSeqs.at(-1) ?? -1
}

function latestStepSeq(step: ProcessStep | undefined): number {
  return step ? latestEntrySeq(step.rawEventSeqs) : -1
}

function summarizeFollowUpAttachments(event: SessionEvent): string[] {
  const attachments = Array.isArray(event.payload.attachments) ? event.payload.attachments : []
  return attachments
    .map((attachment) => {
      if (!attachment || typeof attachment !== 'object') return null
      const record = attachment as Record<string, unknown>
      const name = typeof record.name === 'string' ? record.name.trim() : ''
      const path = typeof record.path === 'string' ? record.path.trim() : ''
      if (!name) return null
      return path ? `${name} · ${path}` : name
    })
    .filter((item): item is string => Boolean(item))
}

function summarizeAttachmentCount(count: number): string | null {
  if (count <= 0) return null
  return `Attached ${count} file${count === 1 ? '' : 's'}`
}

function summarizeHumanInterventionHint(detail: string | null): string {
  const summarizedDetail = compactText(detail ?? undefined, 72)
  return summarizedDetail ? `New input: ${summarizedDetail}` : 'New input added.'
}

function isCountLikeProcessTitle(text: string): boolean {
  return /^\d+\s/.test(text.trim())
}

function summarizeProcessCounts(steps: Array<{ kind: 'step'; step: ProcessStep }>): ProcessCounts {
  const counts = createEmptyProcessCounts()
  for (const entry of steps) {
    mergeProcessCounts(counts, summarizeProcessItemCounts(entry.step.items))
  }

  return counts
}

function summarizeStepTitle(items: ProcessToolItem[]): string {
  const displayItems = uniqueDisplayItems(items)
  if (displayItems.length === 0) return 'Answer formed'
  const first = displayItems[0]
  if (displayItems.length === 1) return first.label
  const failed = displayItems.find((item) => item.status === 'failed')
  if (failed) return failed.label

  return (
    buildCountSummaryText(summarizeProcessItemCounts(displayItems)) ??
    `${displayItems.length} actions`
  )
}

function resolveStepStatus(items: ProcessToolItem[], turnState: TurnState): ProcessEntryStatus {
  if (items.some((item) => item.status === 'failed')) return 'failed'
  if (items.some((item) => item.status === 'running') || turnState === 'running') return 'running'
  return 'completed'
}

function summarizeToolLabel(toolName: string, args: Record<string, unknown> | null): string {
  // --- File primitives (new: read/write/edit, legacy: fs with action) ---
  if (toolName === 'read') {
    const path = displayPath(getString(args ?? {}, 'path'))
    return `Read ${path ?? 'file'}`
  }
  if (toolName === 'write') {
    const path = displayPath(getString(args ?? {}, 'path'))
    return `Write ${path ?? 'file'}`
  }
  if (toolName === 'edit') {
    const path = displayPath(getString(args ?? {}, 'path'))
    const delta = formatEditDelta(args)
    return `Edit ${path ?? 'file'}${delta ? ` · ${delta}` : ''}`
  }
  if (toolName === 'fs') {
    // Legacy unified fs tool — derive from action param
    const action = getString(args ?? {}, 'action') ?? 'read'
    const path = displayPath(getString(args ?? {}, 'path'))
    switch (action) {
      case 'read':
        return `Read ${path ?? 'file'}`
      case 'list':
        return `Inspect ${path ?? 'directory'}`
      case 'edit':
        return `Edit ${path ?? 'file'}${formatEditDelta(args) ? ` · ${formatEditDelta(args)}` : ''}`
      case 'write':
        return `Write ${path ?? 'file'}`
      default:
        return `Use fs on ${path ?? 'path'}`
    }
  }

  // --- Execution (new: bash, legacy: exec) ---
  if (toolName === 'bash' || toolName === 'exec') {
    return `Run ${summarizeCommand(getString(args ?? {}, 'command'))}`
  }

  // --- Collaboration & retrieval ---
  if (toolName === 'spawn') {
    const label = compactText(getString(args ?? {}, 'label') ?? getString(args ?? {}, 'task'))
    return label ? `Delegate subtask · ${label}` : 'Delegate subtask'
  }

  if (toolName === 'recall') {
    const query = compactText(getString(args ?? {}, 'query'), 52)
    return query ? `Recall ${query}` : 'Recall memory'
  }

  if (toolName === 'web_search') {
    const query = compactText(getString(args ?? {}, 'query'), 52)
    return query ? `Search ${query}` : 'Search the web'
  }

  if (toolName === 'web_fetch') {
    const url = getString(args ?? {}, 'url')
    return url ? `Fetch ${compactUrl(url)}` : 'Fetch a web page'
  }

  return `Run ${toolName}`
}

function summarizeToolDetail(
  toolName: string,
  args: Record<string, unknown> | null,
): string | null {
  if (!args) return null

  // --- File primitives (new: read/write/edit, legacy: fs with action) ---
  if (toolName === 'read') {
    return summarizeReadDetail(args)
  }
  if (toolName === 'write') {
    const content = getString(args, 'content')
    return content ? `${countLines(content)} lines` : null
  }
  if (toolName === 'edit') {
    return summarizeEditDetail(args)
  }
  if (toolName === 'fs') {
    const action = getString(args, 'action') ?? 'read'
    if (action === 'read') return summarizeReadDetail(args)
    if (action === 'edit') return summarizeEditDetail(args)
    if (action === 'write') {
      const content = getString(args, 'content')
      return content ? `${countLines(content)} lines` : null
    }
    return null
  }

  // --- Execution (new: bash, legacy: exec) ---
  if (toolName === 'bash' || toolName === 'exec') {
    const command = getString(args, 'command')
    // Show the full command in detail when the label truncated it
    if (command && command.length > 64) return command.trim()
    return null
  }

  if (toolName === 'spawn') return null
  if (toolName === 'recall') return null
  if (toolName === 'web_search') return null
  if (toolName === 'web_fetch') return null

  return compactText(JSON.stringify(args), 120)
}

function summarizeReadDetail(args: Record<string, unknown>): string | null {
  const fragments: string[] = []
  const offset = getFiniteNumber(args, 'offset')
  const limit = getFiniteNumber(args, 'limit')
  if (offset != null) fragments.push(`from line ${offset}`)
  if (limit != null) fragments.push(`up to ${limit} lines`)
  return fragments.length > 0 ? joinSummary(fragments) : null
}

function summarizeEditDetail(args: Record<string, unknown>): string | null {
  const oldText = getString(args, 'old_text')
  const newText = getString(args, 'new_text')
  if (!oldText && !newText) return null
  return `replace ${countLines(oldText)} line${countLines(oldText) === 1 ? '' : 's'} with ${countLines(newText)}`
}

function summarizeToolResult(
  toolName: string,
  args: Record<string, unknown> | null,
  resultSize: number | null,
  exitCode: number | null,
): string | null {
  if (toolName === 'bash' || toolName === 'exec') {
    if (exitCode != null && exitCode !== 0) return `exit ${exitCode}`
  }
  return null
}

function allowInlineResultPreview(toolName: string, args: Record<string, unknown> | null): boolean {
  const suppressed = new Set([
    'fs',
    'read',
    'write',
    'edit',
    'exec',
    'bash',
    'spawn',
    'recall',
    'web_search',
    'web_fetch',
  ])
  return !suppressed.has(toolName)
}

function createEmptyProcessCounts(): ProcessCounts {
  return {
    search: 0,
    fetch: 0,
    recall: 0,
    read: 0,
    edit: 0,
    command: 0,
    subtask: 0,
  }
}

function summarizeProcessItemCounts(items: ProcessToolItem[]): ProcessCounts {
  const counts = createEmptyProcessCounts()

  for (const item of uniqueDisplayItems(items)) {
    const bucket = classifyProcessItem(item)
    if (!bucket) continue
    counts[bucket] += 1
  }

  return counts
}

function mergeProcessCounts(target: ProcessCounts, incoming: ProcessCounts): void {
  for (const key of PROCESS_COUNT_ORDER) {
    target[key] += incoming[key]
  }
}

function buildCountSummaryText(counts: ProcessCounts): string | null {
  const fragments = PROCESS_COUNT_ORDER.flatMap((key) =>
    counts[key] > 0 ? [formatCountFragment(key, counts[key])] : [],
  )
  return fragments.length > 0 ? joinSummary(fragments) : null
}

function classifyProcessItem(item: ProcessToolItem): ProcessCountKey | null {
  switch (item.toolName) {
    case 'read':
      return 'read'
    case 'write':
    case 'edit':
      return 'edit'
    case 'fs':
      // Legacy: classify by label
      return item.label.startsWith('Read') || item.label.startsWith('Inspect') ? 'read' : 'edit'
    case 'bash':
    case 'exec':
      return 'command'
    case 'spawn':
      return 'subtask'
    case 'recall':
      return 'recall'
    case 'web_search':
      return 'search'
    case 'web_fetch':
      return 'fetch'
    default:
      return null
  }
}

function formatCountFragment(key: ProcessCountKey, count: number): string {
  const amount = formatCount(count)

  switch (key) {
    case 'search':
      return `${amount} ${count === 1 ? 'search' : 'searches'}`
    case 'fetch':
      return `${amount} ${count === 1 ? 'fetch' : 'fetches'}`
    case 'recall':
      return `${amount} ${count === 1 ? 'recall' : 'recalls'}`
    case 'read':
      return `${amount} ${count === 1 ? 'read' : 'reads'}`
    case 'edit':
      return `${amount} ${count === 1 ? 'edit' : 'edits'}`
    case 'command':
      return `${amount} ${count === 1 ? 'command' : 'commands'}`
    case 'subtask':
      return `${amount} ${count === 1 ? 'subtask' : 'subtasks'}`
  }
}

function mergeSubtaskResultIntoStep(step: MutableStep, event: SessionEvent): boolean {
  const label = extractSubtaskLabel(event)
  if (!label) return false

  for (const item of step.items.values()) {
    if (item.toolName !== 'spawn') continue
    const itemLabel = extractSpawnItemLabel(item.label)
    if (!itemLabel || !sameSubtaskLabel(itemLabel, label)) continue
    item.status = mergeProcessStatus(item.status, extractSubtaskStatus(event))
    if (item.status === 'failed') {
      item.result = 'subtask failed'
    }
    return true
  }

  return false
}

function readArgs(payload: Record<string, unknown>): Record<string, unknown> | null {
  const raw = payload.args
  return raw && typeof raw === 'object' && !Array.isArray(raw)
    ? (raw as Record<string, unknown>)
    : null
}

function formatEditDelta(args: Record<string, unknown> | null): string | null {
  if (!args) return null
  const oldText = getString(args, 'old_text')
  const newText = getString(args, 'new_text')
  if (!oldText && !newText) return null
  const removed = countLines(oldText)
  const added = countLines(newText)
  return `+${added} -${removed}`
}

function countLines(value: string | undefined): number {
  if (!value) return 0
  return value.split('\n').length
}

function summarizeCommand(command: string | undefined): string {
  const text = compactText(command, 64)
  return text ?? 'command'
}

function summarizeAssistantPreview(text: string | undefined): string | null {
  if (!text) return null
  const cleaned = compactText(text, 88)
  return cleaned
}

function summarizeFailureText(text: string | undefined): string {
  return compactText(text, 140) ?? 'The turn failed before the reply settled.'
}

function displayPath(path: string | undefined): string | null {
  if (!path) return null
  const parts = path.split(/[\\/]/).filter(Boolean)
  return parts.at(-1) ?? path
}

function compactUrl(value: string | undefined): string | null {
  if (!value) return null
  try {
    const url = new URL(value)
    return `${url.host}${url.pathname === '/' ? '' : url.pathname}`
  } catch {
    return compactText(value)
  }
}

function stableArgSignature(args: Record<string, unknown> | null): string {
  if (!args) return 'no-args'
  return stableSerialize(args)
}

function stableSerialize(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableSerialize(item)).join(',')}]`
  }
  if (value && typeof value === 'object') {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, item]) => `${key}:${stableSerialize(item)}`)
      .join(',')}}`
  }
  return JSON.stringify(value)
}

function uniqueDisplayItems(items: ProcessToolItem[]): ProcessToolItem[] {
  const seen = new Set<string>()
  const unique: ProcessToolItem[] = []

  for (const item of items) {
    const key = [item.toolName, item.label, item.detail ?? ''].join('::')
    if (seen.has(key)) continue
    seen.add(key)
    unique.push(item)
  }

  return unique
}

function summarizeInjectedNoteDetail(value: string | undefined): string | null {
  if (!value) return null
  const cleaned = value
    .replace(/^\[HaL [^\]]+\]\s*/i, '')
    .replace(/^kind:\s*[\w.-]+\s+source:\s*[\w.-]+\s*/i, '')
    .replace(/^\[(Context Hint|System Reminder|Runtime Note)\]\s*/i, '')
    .trim()
  return compactText(cleaned || value, 140)
}

function summarizeThreadSnapshotNote(event: SessionEvent, prefix: string): string {
  const directThreads = getStringArray(event.refs, 'threads')
  const threads =
    directThreads.length > 0 ? directThreads : getStringArray(event.refs, 'mounted_threads')
  const summary = summarizeThreads(threads)
  if (summary) return `${prefix}: ${summary}`
  return prefix
}

function summarizeTurnContextNote(event: SessionEvent): string {
  const scope = summarizeThreads(getStringArray(event.refs, 'mounted_threads'))
  const content = getString(event.payload, 'content') ?? ''
  const recallMatch = content.match(/\[Recalled Context\]/i)

  if (scope && recallMatch) return `Turn context prepared for ${scope}, with recalled context`
  if (scope) return `Turn context prepared for ${scope}`
  if (recallMatch) return 'Turn context prepared with recalled context'
  return 'Turn context prepared'
}

function compactText(value: string | undefined, max = 96): string | null {
  if (!value) return null
  const cleaned = value.replace(/\s+/g, ' ').trim()
  if (!cleaned) return null
  return cleaned.length <= max ? cleaned : `${cleaned.slice(0, max - 3)}...`
}

function summarizeThreads(threads: string[]): string | null {
  if (threads.length === 0) return null
  if (threads.length <= 2) return threads.join(', ')
  return `${threads.slice(0, 2).join(', ')} +${threads.length - 2}`
}

function joinSummary(items: string[]): string {
  if (items.length <= 1) return items[0] ?? ''
  if (items.length === 2) return `${items[0]} · ${items[1]}`
  return `${items.slice(0, -1).join(' · ')} · ${items.at(-1)}`
}

function formatCount(value: number): string {
  return value < 1000 ? String(value) : `${(value / 1000).toFixed(1).replace(/\.0$/, '')}k`
}

function isToolEvent(type: string): boolean {
  return (
    type === 'tool.call_started' || type === 'tool.call_completed' || type === 'tool.call_failed'
  )
}

function isSubtaskResultEvent(event: SessionEvent): boolean {
  return (
    event.type === 'subagent.completed' ||
    (event.type === 'message.injected' && getString(event.payload, 'kind') === 'subagent_runtime')
  )
}

function extractSubtaskLabel(event: SessionEvent): string | null {
  const direct = compactText(getString(event.payload, 'label'))
  if (direct) return direct
  if (event.type === 'message.injected') {
    return summarizeInjectedSubtaskLabel(getString(event.payload, 'content'))
  }
  return null
}

function extractSubtaskStatus(event: SessionEvent): ProcessEntryStatus {
  return getString(event.payload, 'status') === 'failed' ? 'failed' : 'completed'
}

function summarizeInjectedSubtaskLabel(content: string | undefined): string | null {
  if (!content) return null
  const match = content.match(/^label:\s*(.+)$/m)
  return compactText(match?.[1])
}

function extractSpawnItemLabel(label: string): string | null {
  const match = label.match(/^Delegate subtask ·\s*(.+)$/)
  return compactText(match?.[1])
}

function sameSubtaskLabel(left: string, right: string): boolean {
  return left.trim().toLowerCase() === right.trim().toLowerCase()
}

function mergeProcessStatus(
  current: ProcessEntryStatus,
  incoming: ProcessEntryStatus,
): ProcessEntryStatus {
  if (current === 'failed' || incoming === 'failed') return 'failed'
  if (current === 'running' || incoming === 'running') return 'running'
  return 'completed'
}

function isRawProcessEvent(type: string): boolean {
  return (
    type === 'context.compiled' ||
    type === 'llm.response_completed' ||
    type === 'tool.call_started' ||
    type === 'tool.call_completed' ||
    type === 'tool.call_failed' ||
    type === 'assistant.message_started' ||
    type === 'assistant.message_completed' ||
    type === 'message.injected' ||
    type === 'hook.injected' ||
    type === 'subagent.completed' ||
    type === 'turn.failed'
  )
}

function dedupe(values: number[]): number[] {
  return [...new Set(values)]
}
