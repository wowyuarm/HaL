import { X } from 'lucide-react'

import { StatusDot } from '@/components/ui/status-dot'
import { compactMarkdownPreviewText } from '@/components/ui/hal-markdown'
import {
  buildTurnProcessView,
  type ProcessEntryStatus,
  type ProcessNote,
  type ProcessStep,
} from '@/lib/process'
import { useHalStore } from '@/lib/store'
import type { SessionEvent } from '@/lib/types'
import { cn } from '@/lib/utils'

const PROCESS_RAIL_WIDTH = 'lg:w-[min(460px,36vw)]'
const PROCESS_TIMELINE_GRID = 'grid grid-cols-[20px,minmax(0,1fr)] gap-2.5'
const PROCESS_TIMELINE_AXIS = 'left-[10px] -translate-x-1/2'
const STEP_ITEM_PREVIEW_LIMIT = 5

export function ProcessRail() {
  const reviewPanel = useHalStore((s) => s.reviewPanel)
  const selectedSessionId = useHalStore((s) => s.selectedSessionId)
  const closeReviewPanel = useHalStore((s) => s.closeReviewPanel)
  const allEvents = useHalStore(
    (s) => (selectedSessionId ? s.sessionEvents[selectedSessionId] : undefined) ?? EMPTY_EVENTS,
  )

  if (reviewPanel?.kind !== 'process') return null

  const turnEvents = allEvents.filter((event) => event.turn_id === reviewPanel.turnId)
  const turnState = deriveTurnState(turnEvents)
  const processView = buildTurnProcessView(turnEvents, turnState)
  const previewHintText = processView.preview.hintText
    ? compactMarkdownPreviewText(processView.preview.hintText)
    : null
  const scopeThreads = extractScopeThreads(turnEvents)

  const body = (
    <div className="flex h-full min-h-0 w-full min-w-0 flex-1 flex-col overflow-hidden">
      <div className="flex shrink-0 flex-col border-b border-subtle px-4 py-[8.5px] md:px-5">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0 flex-1">
            {processView.preview.countSummaryText || previewHintText ? (
              <div className="flex min-w-0 items-center gap-2">
                {previewHintText ? (
                  <>
                    <p className="flex min-w-0 items-center gap-2 text-caption text-hal-muted">
                      <StatusDot state="live" className="h-1.5 w-1.5 shrink-0" />
                      <span className="truncate leading-5">{previewHintText}</span>
                    </p>
                  </>
                ) : null}
                {processView.preview.countSummaryText ? (
                  <>
                    {previewHintText ? <span className="shrink-0 text-hal-muted">·</span> : null}
                    <p
                      className={cn(
                        'shrink-0 text-meta font-medium leading-5',
                        processView.preview.tone === 'danger' ? 'text-danger' : 'text-hal-primary',
                      )}
                    >
                      {processView.preview.countSummaryText}
                    </p>
                  </>
                ) : null}
              </div>
            ) : (
              <p
                className={cn(
                  'whitespace-normal break-words text-meta font-medium leading-5',
                  processView.preview.tone === 'danger' ? 'text-danger' : 'text-hal-primary',
                )}
              >
                {processView.preview.countSummaryText ?? processView.preview.summaryText}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={closeReviewPanel}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-hal-muted transition-colors hover:text-hal-primary"
            aria-label="Close turn details"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        {scopeThreads.length > 0 && (
          <p className="mt-1.5 whitespace-normal break-words text-caption leading-5 text-hal-muted">
            {scopeThreads.join(' · ')}
          </p>
        )}
      </div>

      <div className="hal-scroll-hidden min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden px-4 py-4 md:px-5 md:py-5">
        <div className="min-w-0 space-y-4">
          {processView.entries.length > 0 ? (
            <ProcessTimeline entries={processView.entries} />
          ) : (
            <EmptyBlock text="No process entries were captured for this turn." />
          )}

          <RawRecordsSection events={processView.rawEvents} />
        </div>
      </div>
    </div>
  )

  return (
    <>
      <aside
        className={cn(
          'hidden h-full min-h-0 min-w-0 shrink-0 overflow-hidden border-l border-subtle bg-hal-veil lg:flex',
          PROCESS_RAIL_WIDTH,
        )}
      >
        {body}
      </aside>

      <div
        className="fixed inset-0 z-30 bg-[rgba(36,33,29,0.18)] lg:hidden"
        onClick={closeReviewPanel}
      >
        <aside
          className="hal-paper hal-sheet absolute inset-y-0 right-0 flex w-[min(92vw,31rem)] min-w-0 overflow-hidden border-l border-border bg-hal-float shadow-popover"
          onClick={(event) => event.stopPropagation()}
        >
          {body}
        </aside>
      </div>
    </>
  )
}

function ProcessTimeline({
  entries,
}: {
  entries: ReturnType<typeof buildTurnProcessView>['entries']
}) {
  return (
    <section className="relative">
      <span
        aria-hidden="true"
        className={cn(
          'pointer-events-none absolute bottom-6 top-6 w-px bg-[color:var(--border-subtle)]',
          PROCESS_TIMELINE_AXIS,
        )}
      />
      <div className="relative">
        {entries.map((entry) =>
          entry.kind === 'step' ? (
            <StepEntry key={entry.step.id} step={entry.step} />
          ) : (
            <NoteEntry key={entry.note.id} note={entry.note} />
          ),
        )}
      </div>
    </section>
  )
}

function StepEntry({ step }: { step: ProcessStep }) {
  const groupedItems = groupProcessItems(step.items)
  const intentText = step.summary.trim()
  const primaryText = intentText || step.title
  const secondaryText = intentText && groupedItems.length > 1 ? step.title : null
  const singleInlineItem = groupedItems.length === 1 ? groupedItems[0] : null
  const singleToolHeading = Boolean(singleInlineItem && !intentText)

  return (
    <article className={PROCESS_TIMELINE_GRID}>
      <EntryMarker tone={entryMarkerTone(step.status, step.items.length > 0)} />
      <div className="min-w-0 py-2.5">
        <p
          className={cn(
            'text-hal-primary',
            singleToolHeading
              ? 'text-caption font-medium leading-5'
              : intentText
                ? 'text-[14px] font-medium leading-6 tracking-[-0.01em]'
                : 'text-meta font-medium leading-5',
          )}
        >
          {primaryText}
        </p>
        {secondaryText ? (
          <p className="mt-0.5 text-caption text-hal-muted">{secondaryText}</p>
        ) : null}

        {singleInlineItem ? (
          <InlineStepMeta item={singleInlineItem.item} showLabel={Boolean(intentText)} />
        ) : groupedItems.length > 0 ? (
          <div className="mt-1.5">
            <div className="space-y-1.5">
              {groupedItems.slice(0, STEP_ITEM_PREVIEW_LIMIT).map((item) => (
                <ProcessItemRow key={item.key} item={item} />
              ))}

              {groupedItems.length > STEP_ITEM_PREVIEW_LIMIT ? (
                <details className="group">
                  <summary className="cursor-pointer list-none text-caption text-hal-muted">
                    +{groupedItems.length - STEP_ITEM_PREVIEW_LIMIT} more
                  </summary>
                  <div className="mt-1.5 space-y-1.5">
                    {groupedItems.slice(STEP_ITEM_PREVIEW_LIMIT).map((item) => (
                      <ProcessItemRow key={item.key} item={item} />
                    ))}
                  </div>
                </details>
              ) : null}
            </div>
          </div>
        ) : null}
      </div>
    </article>
  )
}

function InlineStepMeta({
  item,
  showLabel,
}: {
  item: ProcessStep['items'][number]
  showLabel: boolean
}) {
  const showResult = shouldShowItemResult(item)
  if (!showLabel && !item.detail && !showResult) return null
  const isFailed = item.status === 'failed'

  return (
    <div className="mt-1">
      {showLabel ? (
        <p
          className={cn('text-caption font-medium', isFailed ? 'text-danger' : 'text-hal-primary')}
        >
          {item.label}
        </p>
      ) : null}
      {item.detail ? <p className="text-caption leading-5 text-hal-muted">{item.detail}</p> : null}
      {showResult ? (
        <p
          className={cn(
            'mt-0.5 text-caption leading-5',
            isFailed ? 'text-danger/80' : 'text-hal-muted',
          )}
        >
          {compactText(item.result, 160)}
        </p>
      ) : null}
    </div>
  )
}

type GroupedProcessItem = {
  key: string
  item: ProcessStep['items'][number]
}

function ProcessItemRow({ item }: { item: GroupedProcessItem }) {
  const showResult = shouldShowItemResult(item.item)
  const isFailed = item.item.status === 'failed'

  return (
    <div className="min-w-0">
      <div className="flex items-center gap-2">
        <p
          className={cn('text-caption font-medium', isFailed ? 'text-danger' : 'text-hal-primary')}
        >
          {item.item.label}
        </p>
      </div>
      {item.item.detail ? (
        <p className="mt-0.5 text-caption leading-5 text-hal-muted">{item.item.detail}</p>
      ) : null}
      {showResult ? (
        <p
          className={cn(
            'mt-0.5 text-caption leading-5',
            isFailed ? 'text-danger/80' : 'text-hal-muted',
          )}
        >
          {compactText(item.item.result, 160)}
        </p>
      ) : null}
    </div>
  )
}

function shouldShowItemResult(item: ProcessStep['items'][number]): boolean {
  const result = item.result?.trim()
  return Boolean(result)
}

function groupProcessItems(items: ProcessStep['items']): GroupedProcessItem[] {
  const groups = new Map<string, GroupedProcessItem>()

  for (const item of items) {
    const key = [item.toolName, item.label, item.detail ?? ''].join('::')
    const existing = groups.get(key)
    if (existing) {
      existing.item.status = mergeItemStatus(existing.item.status, item.status)
      existing.item.result = existing.item.result ?? item.result
      continue
    }
    groups.set(key, {
      key,
      item,
    })
  }

  return [...groups.values()]
}

function mergeItemStatus(
  current: ProcessEntryStatus,
  incoming: ProcessEntryStatus,
): ProcessEntryStatus {
  if (current === 'failed' || incoming === 'failed') return 'failed'
  if (current === 'running' || incoming === 'running') return 'running'
  return 'completed'
}

function NoteEntry({ note }: { note: ProcessNote }) {
  const noteLabel = formatNoteLabel(note.label)
  const markerTone: 'hal' | 'human' | 'muted' | 'danger' =
    note.tone === 'danger' ? 'danger' : note.tone === 'human-authored' ? 'human' : 'muted'

  return (
    <article className={PROCESS_TIMELINE_GRID}>
      <EntryMarker tone={markerTone} offsetClass={noteLabel ? 'pt-3.5' : 'pt-4'} />
      <div className="min-w-0 py-2.5">
        {noteLabel ? (
          <p className="text-[10.5px] font-medium uppercase leading-4 tracking-[0.14em] text-hal-muted">
            {noteLabel}
          </p>
        ) : null}
        {note.detail ? (
          <p
            className={cn(
              'leading-5',
              noteLabel ? 'mt-1 text-caption text-hal-primary' : 'text-caption text-hal-muted',
            )}
          >
            {note.detail}
          </p>
        ) : null}
        {note.items && note.items.length > 0 ? (
          <div className="mt-1.5 space-y-1">
            {note.items.map((item) => (
              <p key={item} className="text-caption leading-5 text-hal-muted">
                {item}
              </p>
            ))}
          </div>
        ) : null}
      </div>
    </article>
  )
}

function EntryMarker({
  tone,
  offsetClass = 'pt-4',
}: {
  tone: 'hal' | 'human' | 'muted' | 'danger'
  offsetClass?: string
}) {
  return (
    <div className={cn('flex justify-center', offsetClass)}>
      <span
        className={cn(
          'h-2 w-2 shrink-0 rounded-full',
          tone === 'danger'
            ? 'bg-danger'
            : tone === 'human'
              ? 'bg-human'
              : tone === 'hal'
                ? 'bg-accent'
                : 'bg-hal-muted opacity-60',
        )}
      />
    </div>
  )
}

function RawRecordsSection({ events }: { events: SessionEvent[] }) {
  return (
    <section className="bg-hal-paper/60 w-full min-w-0 overflow-hidden rounded-md border border-subtle">
      <details className="group block w-full min-w-0">
        <summary className="block w-full cursor-pointer list-none px-4 py-3">
          <div className="flex items-center justify-between gap-4">
            <p className="hal-meta-kicker">Raw records</p>
            <p className="text-caption text-hal-muted">
              {events.length} event{events.length === 1 ? '' : 's'}
            </p>
          </div>
        </summary>
        <div className="bg-hal-inset/25 min-w-0 border-t border-subtle px-3 py-3">
          {events.length > 0 ? (
            <div className="divide-subtle/80 min-w-0 divide-y overflow-hidden rounded-sm bg-white/30">
              {events.map((event, index) => (
                <RawEventRow key={event.seq} event={event} first={index === 0} />
              ))}
            </div>
          ) : (
            <p className="px-1 text-caption text-hal-muted">No raw records available.</p>
          )}
        </div>
      </details>
    </section>
  )
}

function RawEventRow({ event, first }: { event: SessionEvent; first: boolean }) {
  const payloadText = formatRawJson(event.payload)
  const refsText = hasRecordContent(event.refs) ? formatRawJson(event.refs) : null

  return (
    <details className="group block w-full min-w-0 overflow-hidden">
      <summary className="grid w-full min-w-0 cursor-pointer list-none grid-cols-[auto,minmax(0,1fr),auto] items-start gap-3 px-3 py-3">
        <span className="pt-[1px] font-mono text-[10.5px] text-hal-muted">#{event.seq}</span>
        <div className="min-w-0">
          <p className="font-mono text-[11px] leading-4 text-hal-primary">{event.type}</p>
          <p className="mt-1 text-caption leading-5 text-hal-muted">{summarizeRawEvent(event)}</p>
        </div>
        <p className="pt-[1px] text-caption text-hal-muted">{event.actor}</p>
      </summary>

      <div
        className={cn(
          'bg-hal-inset/30 min-w-0 space-y-3 px-3 py-3',
          first ? 'border-subtle/80 border-t' : 'border-subtle/60 border-t',
        )}
      >
        {refsText ? <RawJsonBlock label="refs" value={refsText} /> : null}
        <RawJsonBlock label="payload" value={payloadText} />
      </div>
    </details>
  )
}

function RawJsonBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <p className="text-[10.5px] font-medium uppercase tracking-[0.14em] text-hal-muted">
        {label}
      </p>
      <pre className="mt-2 whitespace-pre-wrap break-all rounded-sm bg-white/35 px-3 py-2.5 font-mono text-[11px] leading-5 text-hal-muted">
        {value}
      </pre>
    </div>
  )
}

function EmptyBlock({ text }: { text: string }) {
  return (
    <div className="bg-hal-inset/70 rounded-md border border-dashed border-subtle px-4 py-6 text-center">
      <p className="text-meta text-hal-muted">{text}</p>
    </div>
  )
}

function summarizeRawEvent(event: SessionEvent): string {
  const payloadKeys = summarizeObjectKeys(event.payload)
  const refsKeys = summarizeObjectKeys(event.refs)
  if (payloadKeys && refsKeys) return `payload: ${payloadKeys} · refs: ${refsKeys}`
  if (payloadKeys) return `payload: ${payloadKeys}`
  if (refsKeys) return `refs: ${refsKeys}`
  return 'No extra fields.'
}

function summarizeObjectKeys(record: Record<string, unknown>): string | null {
  const keys = Object.keys(record)
  if (keys.length === 0) return null
  if (keys.length <= 3) return keys.join(', ')
  return `${keys.slice(0, 3).join(', ')} +${keys.length - 3}`
}

function hasRecordContent(record: Record<string, unknown>): boolean {
  return Object.keys(record).length > 0
}

function formatRawJson(record: Record<string, unknown>): string {
  if (!hasRecordContent(record)) return '{}'
  return JSON.stringify(record, null, 2)
}

function deriveTurnState(events: SessionEvent[]): ProcessEntryStatus {
  if (events.some((event) => event.type === 'turn.failed')) return 'failed'
  if (events.some((event) => event.type === 'turn.completed')) return 'completed'
  return 'running'
}

/** Extract mounted + recalled thread slugs from the context.compiled event. */
function extractScopeThreads(events: SessionEvent[]): string[] {
  const compiled = events.find((event) => event.type === 'context.compiled')
  if (!compiled) return []
  const mounted = Array.isArray(compiled.refs.mounted_threads)
    ? (compiled.refs.mounted_threads as unknown[]).filter(
        (item): item is string => typeof item === 'string' && item.length > 0,
      )
    : []
  const recalled = Array.isArray(compiled.refs.recalled_threads)
    ? (compiled.refs.recalled_threads as unknown[]).filter(
        (item): item is string => typeof item === 'string' && item.length > 0,
      )
    : []
  return [...new Set([...mounted, ...recalled])]
}

function compactText(value: string | null | undefined, max = 120): string | null {
  if (!value) return null
  const cleaned = value.replace(/\s+/g, ' ').trim()
  if (!cleaned) return null
  return cleaned.length <= max ? cleaned : `${cleaned.slice(0, max - 3)}...`
}

function entryMarkerTone(
  status: ProcessEntryStatus,
  useHalAccent: boolean,
): 'hal' | 'muted' | 'danger' {
  if (status === 'failed') return 'danger'
  if (useHalAccent) return 'hal'
  return 'muted'
}

function formatNoteLabel(label: string): string | null {
  if (label === 'note') return null
  return label
    .split(/[_-]+/)
    .filter(Boolean)
    .map((part) => part.slice(0, 1).toUpperCase() + part.slice(1))
    .join(' ')
}

const EMPTY_EVENTS: SessionEvent[] = []
