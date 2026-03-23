import { eventSummary, formatCount } from '@/lib/runtime'
import type { EvidenceCounts } from '@/lib/session-adapter'
import type { SessionEvent } from '@/lib/types'

export const EVIDENCE_CATEGORY_ORDER = ['context', 'loop', 'tool', 'injection', 'worker'] as const

export type EvidenceCategoryKey = (typeof EVIDENCE_CATEGORY_ORDER)[number] | 'other'

interface EvidenceCategoryMeta {
  label: string
  shortLabel: string
  description: string
  singularRecord: string
  pluralRecord: string
}

export const EVIDENCE_CATEGORY_META: Record<EvidenceCategoryKey, EvidenceCategoryMeta> = {
  context: {
    label: 'Context record',
    shortLabel: 'Context',
    description: 'What working material and recalled threads informed this turn.',
    singularRecord: 'context snapshot',
    pluralRecord: 'context snapshots',
  },
  loop: {
    label: 'Execution trace',
    shortLabel: 'Execution',
    description: 'How HaL stepped through planning, drafting, and model calls.',
    singularRecord: 'execution trace',
    pluralRecord: 'execution traces',
  },
  tool: {
    label: 'Tool trace',
    shortLabel: 'Tool',
    description: 'Which tools were prepared or invoked during the turn.',
    singularRecord: 'tool trace',
    pluralRecord: 'tool traces',
  },
  injection: {
    label: 'Injected note',
    shortLabel: 'Injected',
    description: 'Contextual notes or runtime insertions surfaced into the turn.',
    singularRecord: 'injected note',
    pluralRecord: 'injected notes',
  },
  worker: {
    label: 'Worker handoff',
    shortLabel: 'Worker',
    description: 'Background workers or briefing tasks attached to the turn.',
    singularRecord: 'worker handoff',
    pluralRecord: 'worker handoffs',
  },
  other: {
    label: 'Record',
    shortLabel: 'Other',
    description: 'Additional evidence captured for review.',
    singularRecord: 'record',
    pluralRecord: 'records',
  },
}

export interface EvidenceEventDescriptor {
  category: EvidenceCategoryKey
  title: string
  detail: string | null
}

export function evidenceCategory(type: string): EvidenceCategoryKey {
  if (type === 'context.compiled') return 'context'
  if (type.startsWith('loop.') || type.startsWith('llm.') || type === 'assistant.message_started') {
    return 'loop'
  }
  if (type === 'tool.call_started') return 'tool'
  if (type === 'hook.injected') return 'injection'
  if (type === 'subagent.spawned' || type === 'brief.started') return 'worker'
  return 'other'
}

export function evidenceCountEntries(
  counts: EvidenceCounts,
): Array<{ key: EvidenceCategoryKey; count: number }> {
  return EVIDENCE_CATEGORY_ORDER.map((key) => ({ key, count: counts[key] })).filter(
    (entry) => entry.count > 0,
  )
}

export function summarizeEvidenceKinds(counts: EvidenceCounts, limit = 3): string {
  const labels = evidenceCountEntries(counts)
    .slice(0, limit)
    .map(({ key }) => EVIDENCE_CATEGORY_META[key].shortLabel.toLowerCase())

  if (labels.length === 0) return 'Trace available'
  if (labels.length === 1) return `${labels[0]} evidence`
  if (labels.length === 2) return `${labels[0]} and ${labels[1]} evidence`
  return `${labels.slice(0, -1).join(', ')}, and ${labels.at(-1)} evidence`
}

export function summarizeEvidenceCounts(counts: EvidenceCounts): string {
  const entries = evidenceCountEntries(counts)
  if (entries.length === 0) return 'No evidence was recorded for this turn.'

  const fragments = entries.map(({ key, count }) => {
    const meta = EVIDENCE_CATEGORY_META[key]
    const noun = count === 1 ? meta.singularRecord : meta.pluralRecord
    return `${formatCount(count)} ${noun}`
  })

  return `${joinList(fragments)} recorded for this turn.`
}

export function describeEvidenceEvent(event: SessionEvent): EvidenceEventDescriptor {
  switch (event.type) {
    case 'context.compiled':
      return {
        category: 'context',
        title: eventSummary(event),
        detail: joinFragments([
          formatThreadFragment('mounted', event.refs.mounted_threads),
          formatThreadFragment('recalled', event.refs.recalled_threads),
          formatCountFragment('working set', event.payload.working_set_messages, 'msg'),
          formatCountFragment('history', event.payload.history_messages, 'msg'),
        ]),
      }
    case 'loop.started':
      return {
        category: 'loop',
        title: 'Execution loop opened',
        detail: joinFragments([formatStringFragment('model', event.payload.model)]),
      }
    case 'loop.iteration_started':
      return {
        category: 'loop',
        title: eventSummary(event),
        detail: joinFragments([formatCountFragment('iteration', event.payload.iteration)]),
      }
    case 'llm.request_started':
      return {
        category: 'loop',
        title: 'Model request prepared',
        detail: joinFragments([
          formatStringFragment('model', event.payload.model),
          formatCountFragment('messages', event.payload.message_count),
          formatCountFragment('tools', event.payload.tool_count),
        ]),
      }
    case 'llm.response_completed':
      return {
        category: 'loop',
        title: Boolean(event.payload.has_tool_calls)
          ? 'Model response proposed tool work'
          : 'Model response completed',
        detail: joinFragments([
          formatCountFragment('output', event.payload.output_tokens, 'tok'),
          formatCountFragment('reasoning', event.payload.reasoning_tokens, 'tok'),
          formatCountFragment('tool calls', event.payload.tool_call_count),
        ]),
      }
    case 'assistant.message_started':
      return {
        category: 'loop',
        title: 'Response drafting started',
        detail: null,
      }
    case 'tool.call_started':
      return {
        category: 'tool',
        title: eventSummary(event),
        detail: joinFragments([
          formatStringFragment('call', event.refs.tool_call_id),
          formatJsonFragment('args', event.payload.args),
        ]),
      }
    case 'hook.injected':
      return {
        category: 'injection',
        title: eventSummary(event),
        detail: joinFragments([
          formatStringFragment('source', event.payload.source),
          formatTextFragment(event.payload.content),
        ]),
      }
    case 'subagent.spawned':
      return {
        category: 'worker',
        title: `Worker spawned: ${stringValue(event.payload.label) ?? 'subagent'}`,
        detail: joinFragments([
          formatStringFragment('kind', event.payload.kind),
          formatTextFragment(event.payload.task),
        ]),
      }
    case 'brief.started':
      return {
        category: 'worker',
        title: 'Brief compilation started',
        detail: joinFragments([formatStringFragment('thread', event.refs.thread_slug)]),
      }
    default:
      return {
        category: evidenceCategory(event.type),
        title: eventSummary(event),
        detail: joinFragments([
          formatJsonFragment('payload', event.payload),
          formatJsonFragment('refs', event.refs),
        ]),
      }
  }
}

function joinList(parts: string[]): string {
  if (parts.length <= 1) return parts[0] ?? ''
  if (parts.length === 2) return `${parts[0]} and ${parts[1]}`
  return `${parts.slice(0, -1).join(', ')}, and ${parts.at(-1)}`
}

function joinFragments(parts: Array<string | null>): string | null {
  const compact = parts.filter((part): part is string => Boolean(part))
  return compact.length > 0 ? compact.join(' · ') : null
}

function formatThreadFragment(label: string, value: unknown): string | null {
  const items = stringList(value)
  if (items.length === 0) return null
  if (items.length <= 2) return `${label} ${items.join(', ')}`
  return `${label} ${items.slice(0, 2).join(', ')} +${items.length - 2}`
}

function formatCountFragment(label: string, value: unknown, suffix?: string): string | null {
  const count = numberValue(value)
  if (count == null) return null
  return `${label} ${formatCount(count)}${suffix ? ` ${suffix}` : ''}`
}

function formatStringFragment(label: string, value: unknown): string | null {
  const text = stringValue(value)
  return text ? `${label} ${text}` : null
}

function formatTextFragment(value: unknown): string | null {
  const text = stringValue(value)
  return text ? truncate(text.replace(/\s+/g, ' '), 160) : null
}

function formatJsonFragment(label: string, value: unknown): string | null {
  if (!value || typeof value !== 'object') return null
  if (Array.isArray(value) && value.length === 0) return null
  if (!Array.isArray(value) && Object.keys(value as Record<string, unknown>).length === 0) {
    return null
  }
  return `${label} ${truncate(JSON.stringify(value), 160)}`
}

function truncate(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 3)}...`
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null
}

function numberValue(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string' && item.length > 0)
    : []
}
