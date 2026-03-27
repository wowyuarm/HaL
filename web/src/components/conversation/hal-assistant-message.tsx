/**
 * HalAssistantMessage — renders assistant output with a lightweight process strip.
 *
 * Uses assistant-ui primitives for context binding. Text parts render through
 * the shared HaL markdown renderer. Process visibility is handled by a quiet
 * evidence seam strip above the answer body.
 */

import { MessagePrimitive, useMessage } from '@assistant-ui/react'
import type { TextMessagePartProps } from '@assistant-ui/react'
import { ChevronRight } from 'lucide-react'

import { HalMarkdown } from '@/components/ui/hal-markdown'
import { StatusDot } from '@/components/ui/status-dot'
import type { HalMessageMeta } from '@/lib/session-adapter'
import { useHalStore } from '@/lib/store'
import { cn } from '@/lib/utils'

export function HalAssistantMessage() {
  const isRunning = useMessage((s) => s.status?.type === 'running')
  const isFailed = useMessage((s) => s.status?.type === 'incomplete')
  const custom = useMessage((s) => s.metadata?.custom as HalMessageMeta | undefined)
  const firstText = useMessage((s) => {
    const part = s.content.find((item) => item.type === 'text')
    return part?.type === 'text' ? part.text : ''
  })
  const openProcessPanel = useHalStore((s) => s.openProcessPanel)
  const processPanel = useHalStore((s) => s.reviewPanel)
  const isCommand = custom?.isCommand === true
  const isBriefLifecycle = custom?.lifecycleKind === 'brief'
  const currentSessionStatus = useHalStore((s) =>
    s.selectedSessionId ? (s.sessionManifests[s.selectedSessionId]?.status ?? null) : null,
  )
  const showBriefLiveDot =
    isBriefLifecycle && custom?.lifecycleState === 'start' && currentSessionStatus === 'briefing'
  const processPreview = custom?.processPreview
  const processOpen = processPanel?.kind === 'process' && processPanel.turnId === custom?.turnId
  const directOnlyProcess =
    processPreview?.summaryText === 'replied directly' &&
    processPreview.stepCount === 1 &&
    processPreview.noteCount === 0
  const processAriaLabel = processPreview
    ? buildProcessAriaLabel(
        processPreview.hintText,
        processPreview.countSummaryText,
        processPreview.summaryText,
      )
    : null

  // Command responses: compact inline row, no bubble.
  if (isCommand) {
    const commandText = isFailed ? summarizeErrorText(firstText) : firstText
    return (
      <MessagePrimitive.Root className="px-1 py-1.5">
        <div className="flex min-w-0 items-center gap-2">
          {isRunning && <StatusDot state="live" />}
          {!isRunning && showBriefLiveDot && <StatusDot state="live" />}
          {isBriefLifecycle && (
            <span className="shrink-0 text-caption font-medium uppercase tracking-[0.08em] text-hal-muted">
              Brief
            </span>
          )}
          {commandText && (
            <span className={isFailed ? 'text-meta text-danger' : 'text-meta text-hal-primary'}>
              {commandText}
            </span>
          )}
        </div>
      </MessagePrimitive.Root>
    )
  }

  return (
    <MessagePrimitive.Root
      className={
        isFailed ? 'rounded-md border border-danger bg-hal-danger-subtle px-4 py-3.5' : 'px-1 py-2'
      }
    >
      {custom?.turnId && processPreview && (
        <button
          type="button"
          onClick={() => openProcessPanel(custom.turnId!)}
          aria-label={`Turn process: ${processAriaLabel ?? processPreview.summaryText}`}
          className={cn(
            "group relative isolate mb-1 flex w-full items-start gap-2 py-1.5 pr-1.5 text-left transition-all duration-fast ease-standard before:pointer-events-none before:absolute before:inset-0 before:rounded-lg before:transition-all before:duration-fast before:ease-standard before:content-['']",
            processOpen
              ? 'before:-inset-x-0.5 before:-inset-y-0.5 before:rounded-xl before:bg-hal-hover'
              : directOnlyProcess
                ? 'opacity-45 hover:opacity-75 hover:before:-inset-x-0.5 hover:before:-inset-y-0.5 hover:before:rounded-xl hover:before:bg-hal-hover'
                : 'hover:before:-inset-x-0.5 hover:before:-inset-y-0.5 hover:before:rounded-xl hover:before:bg-hal-hover',
          )}
        >
          <span
            className={cn(
              'relative z-10 h-4 w-[2px] shrink-0 self-center rounded-full transition-colors duration-fast ease-standard',
              processPreview.tone === 'danger'
                ? 'bg-danger'
                : processOpen
                  ? 'bg-[color:var(--turn-seam-active)]'
                  : 'bg-[color:var(--turn-seam-color)] group-hover:bg-[color:var(--turn-seam-active)]',
            )}
          />
          <span className="relative z-10 flex min-w-0 flex-1 items-center gap-2">
            {processPreview.hintText ? (
              <span className="flex min-w-0 flex-1 items-center gap-2">
                <StatusDot state="live" className="h-1.5 w-1.5 shrink-0" />
                <span className="truncate text-meta leading-5 text-hal-primary">
                  {processPreview.hintText}
                </span>
              </span>
            ) : !processPreview.countSummaryText ? (
              <span
                className={cn(
                  'block min-w-0 whitespace-normal break-words text-meta leading-5',
                  processPreview.tone === 'danger' ? 'text-danger' : 'text-hal-muted',
                )}
              >
                {processPreview.summaryText}
              </span>
            ) : null}
            {processPreview.countSummaryText ? (
              <>
                {processPreview.hintText ? (
                  <span className="shrink-0 text-hal-muted">·</span>
                ) : null}
                <span
                  className={cn(
                    'shrink-0 text-meta leading-5',
                    processPreview.tone === 'danger' ? 'text-danger' : 'text-hal-muted',
                  )}
                >
                  {processPreview.countSummaryText}
                </span>
              </>
            ) : null}
          </span>
          {!directOnlyProcess && (
            <ChevronRight
              className={cn(
                'relative z-10 h-3 w-3 shrink-0 self-center text-hal-muted transition-all duration-fast ease-standard',
                processOpen ? 'rotate-90 opacity-60' : 'opacity-0 group-hover:opacity-50',
              )}
            />
          )}
        </button>
      )}

      {!processPreview && custom?.origin === 'background_resume' ? (
        <div className="mb-2 flex items-center gap-2">
          <span className="text-caption font-medium uppercase tracking-[0.1em] text-hal-muted">
            background
          </span>
        </div>
      ) : null}

      <MessagePrimitive.Content components={ASSISTANT_CONTENT_COMPONENTS} />
    </MessagePrimitive.Root>
  )
}

function AssistantTextPart({ text }: TextMessagePartProps) {
  if (!text?.trim()) return null

  return <HalMarkdown>{text}</HalMarkdown>
}

// ---------------------------------------------------------------------------
// Error text helpers
// ---------------------------------------------------------------------------

function summarizeErrorText(text: string): string {
  const jsonMessage = extractJsonMessage(text)
  return truncate((jsonMessage ?? text).replace(/\s+/g, ' ').trim(), 180)
}

function extractJsonMessage(text: string): string | null {
  const start = text.indexOf('{')
  const end = text.lastIndexOf('}')
  if (start === -1 || end <= start) return null

  try {
    const parsed = JSON.parse(text.slice(start, end + 1)) as unknown
    if (!parsed || typeof parsed !== 'object') return null
    const obj = parsed as Record<string, unknown>
    // Try common error shape: { error: { message: "..." } } or { message: "..." }
    if (typeof obj.message === 'string') return obj.message
    if (obj.error && typeof obj.error === 'object') {
      const inner = obj.error as Record<string, unknown>
      if (typeof inner.message === 'string') return inner.message
    }
    return null
  } catch {
    return null
  }
}

function truncate(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 3)}...`
}

function buildProcessAriaLabel(
  hintText: string | null,
  countSummaryText: string | null,
  summaryText: string,
): string {
  if (hintText && countSummaryText) return `${hintText}. ${countSummaryText}.`
  if (hintText) return hintText
  return countSummaryText ?? summaryText
}

const ASSISTANT_CONTENT_COMPONENTS = {
  Text: AssistantTextPart,
} as const
