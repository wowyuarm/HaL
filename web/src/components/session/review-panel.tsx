import { useEffect, useState } from 'react'

import { ReadingPanel } from '@/components/layout/reading-panel'
import { HalMarkdown } from '@/components/ui/hal-markdown'
import {
  describeEvidenceEvent,
  EVIDENCE_CATEGORY_META,
  EVIDENCE_CATEGORY_ORDER,
  evidenceCategory,
  evidenceCountEntries,
  summarizeEvidenceCounts,
} from '@/lib/evidence'
import { getThreadEpisode } from '@/lib/api'
import { formatTimestamp } from '@/lib/runtime'
import { EVIDENCE_EVENTS } from '@/lib/session-adapter'
import { useHalStore } from '@/lib/store'
import type { SessionEvent, ThreadEpisode } from '@/lib/types'

const REVIEW_PANEL_WIDTH = 'w-[min(520px,42vw)]'

interface ReviewPanelProps {
  briefMarkdown: string | null
  threadSlug: string | null
}

type EpisodeLoadState =
  | { status: 'idle'; episode: null; error: null }
  | { status: 'loading'; episode: null; error: null }
  | { status: 'ready'; episode: ThreadEpisode; error: null }
  | { status: 'error'; episode: null; error: string }

const INITIAL_EPISODE_STATE: EpisodeLoadState = {
  status: 'idle',
  episode: null,
  error: null,
}

export function ReviewPanel({ briefMarkdown, threadSlug }: ReviewPanelProps) {
  const reviewPanel = useHalStore((s) => s.reviewPanel)
  const selectedSessionId = useHalStore((s) => s.selectedSessionId)
  const allEvents = useHalStore(
    (s) => (selectedSessionId ? s.sessionEvents[selectedSessionId] : undefined) ?? EMPTY_EVENTS,
  )
  const closeReviewPanel = useHalStore((s) => s.closeReviewPanel)
  const openEpisode = useHalStore((s) => s.openEpisode)
  const [episodeState, setEpisodeState] = useState<EpisodeLoadState>(INITIAL_EPISODE_STATE)

  useEffect(() => {
    if (reviewPanel?.kind !== 'episode') {
      setEpisodeState(INITIAL_EPISODE_STATE)
      return
    }

    let cancelled = false
    setEpisodeState({ status: 'loading', episode: null, error: null })

    void getThreadEpisode(reviewPanel.threadSlug, reviewPanel.episodePath)
      .then((episode) => {
        if (cancelled) return
        setEpisodeState({ status: 'ready', episode, error: null })
      })
      .catch((error) => {
        if (cancelled) return
        setEpisodeState({
          status: 'error',
          episode: null,
          error: error instanceof Error ? error.message : 'Failed to load episode preview.',
        })
      })

    return () => {
      cancelled = true
    }
  }, [reviewPanel])

  if (!reviewPanel) return null

  const activeThreadSlug = reviewPanel.kind === 'episode' ? reviewPanel.threadSlug : threadSlug
  const handleEpisodeLinkClick = (href: string) => {
    const episodePath = normalizeEpisodeHref(href)
    if (!episodePath || !activeThreadSlug) return
    openEpisode({
      threadSlug: activeThreadSlug,
      episodePath,
      episodeTitle: episodeTitleFromPath(episodePath),
    })
  }

  if (reviewPanel.kind === 'brief') {
    return (
      <ReadingPanel
        open
        title="Brief"
        description="Current thread synthesis, carried across sessions."
        widthClassName={REVIEW_PANEL_WIDTH}
        zIndexClassName="z-30"
        onClose={closeReviewPanel}
      >
        <HalMarkdown tone="brief" onLinkClick={handleEpisodeLinkClick}>
          {briefMarkdown || '_This thread does not have a brief yet._'}
        </HalMarkdown>
      </ReadingPanel>
    )
  }

  if (reviewPanel.kind === 'episode') {
    const episode = episodeState.episode
    return (
      <ReadingPanel
        open
        title="Episode"
        description="Archived thread note from a briefed session."
        widthClassName={REVIEW_PANEL_WIDTH}
        zIndexClassName="z-30"
        onClose={closeReviewPanel}
      >
        {episodeState.status === 'loading' ? (
          <div className="bg-hal-inset/70 rounded-md border border-dashed border-subtle px-4 py-6 text-center">
            <p className="text-meta text-hal-muted">Loading episode preview...</p>
          </div>
        ) : episodeState.status === 'error' ? (
          <div className="rounded-md border border-danger bg-hal-danger-subtle px-4 py-6 text-center">
            <p className="text-meta font-medium text-danger">Episode could not be loaded.</p>
            <p className="mt-1 text-caption text-hal-muted">{episodeState.error}</p>
          </div>
        ) : episode ? (
          <HalMarkdown tone="brief" onLinkClick={handleEpisodeLinkClick}>
            {episode.markdown}
          </HalMarkdown>
        ) : (
          <div className="bg-hal-inset/70 rounded-md border border-dashed border-subtle px-4 py-6 text-center">
            <p className="text-meta text-hal-muted">No episode content available.</p>
          </div>
        )}
      </ReadingPanel>
    )
  }

  const turnId = reviewPanel.turnId
  const evidenceEvents = allEvents.filter(
    (e) => e.turn_id === turnId && EVIDENCE_EVENTS.has(e.type),
  )
  const sections = buildEvidenceSections(evidenceEvents)
  const counts = countByCategory(evidenceEvents)
  const summary = summarizeEvidenceCounts(counts)
  const compactEntries = evidenceCountEntries(counts)

  return (
    <ReadingPanel
      open
      title="Evidence"
      description={summary}
      meta={
        <>
          <p className="font-mono text-caption text-hal-muted">{turnId}</p>
          {compactEntries.length > 0 ? (
            <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-caption text-hal-muted">
              {compactEntries.map(({ key, count }) => (
                <span key={key}>
                  {EVIDENCE_CATEGORY_META[key].shortLabel} {count}
                </span>
              ))}
            </div>
          ) : null}
        </>
      }
      widthClassName={REVIEW_PANEL_WIDTH}
      zIndexClassName="z-30"
      onClose={closeReviewPanel}
    >
      {evidenceEvents.length === 0 ? (
        <div className="bg-hal-inset/70 rounded-md border border-dashed border-subtle px-4 py-6 text-center">
          <p className="text-meta text-hal-muted">No evidence records for this turn.</p>
        </div>
      ) : (
        <div className="space-y-6">
          {sections.map((section) => (
            <section key={section.key} className="space-y-2.5">
              <div className="flex items-baseline justify-between gap-3 border-b border-subtle pb-2">
                <div>
                  <p className="hal-meta-kicker">{EVIDENCE_CATEGORY_META[section.key].label}</p>
                  <p className="mt-1 text-caption text-hal-muted">
                    {EVIDENCE_CATEGORY_META[section.key].description}
                  </p>
                </div>
                <span className="shrink-0 text-caption text-hal-muted">
                  {section.events.length} record{section.events.length === 1 ? '' : 's'}
                </span>
              </div>
              <div className="space-y-0">
                {section.events.map((event, index) => (
                  <EvidenceRow
                    key={event.seq}
                    event={event}
                    bordered={index < section.events.length - 1}
                  />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </ReadingPanel>
  )
}

function EvidenceRow({ event, bordered }: { event: SessionEvent; bordered: boolean }) {
  const descriptor = describeEvidenceEvent(event)

  return (
    <article
      className={bordered ? 'border-subtle/80 border-b pb-3 pt-3 first:pt-0' : 'pt-3 first:pt-0'}
    >
      <div className="grid grid-cols-[72px,minmax(0,1fr)] gap-3">
        <div className="pt-0.5 text-caption text-hal-muted">
          <span title={formatTimestamp(event.ts)}>{formatTime(event.ts)}</span>
        </div>
        <div className="min-w-0 border-l border-subtle pl-3">
          <p className="text-meta font-medium text-hal-primary">{descriptor.title}</p>
          <p className="mt-1 font-mono text-caption text-hal-muted">{event.type}</p>
          {descriptor.detail && (
            <p className="mt-2 font-mono text-caption leading-6 text-hal-muted">
              {descriptor.detail}
            </p>
          )}
        </div>
      </div>
    </article>
  )
}

type EvidenceSection = {
  key: (typeof EVIDENCE_CATEGORY_ORDER)[number]
  events: SessionEvent[]
}

function buildEvidenceSections(events: SessionEvent[]): EvidenceSection[] {
  return EVIDENCE_CATEGORY_ORDER.map((key) => ({
    key,
    events: events.filter((event) => evidenceCategory(event.type) === key),
  })).filter((section): section is EvidenceSection => section.events.length > 0)
}

function countByCategory(
  events: SessionEvent[],
): Record<(typeof EVIDENCE_CATEGORY_ORDER)[number], number> {
  const counts: Record<(typeof EVIDENCE_CATEGORY_ORDER)[number], number> = {
    context: 0,
    loop: 0,
    tool: 0,
    injection: 0,
    worker: 0,
  }
  for (const event of events) {
    const category = evidenceCategory(event.type)
    if (category in counts) counts[category as keyof typeof counts] += 1
  }
  return counts
}

function formatTime(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString('en-US', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return ts
  }
}

function normalizeEpisodeHref(href: string): string | null {
  const normalized = href.startsWith('./') ? href.slice(2) : href
  if (!normalized.startsWith('episodes/')) return null
  return normalized
}

function episodeTitleFromPath(episodePath: string): string {
  const lastSegment = episodePath.split('/').filter(Boolean).at(-1)
  if (!lastSegment) return 'Episode'
  return lastSegment.replace(/\.md$/i, '')
}

const EMPTY_EVENTS: SessionEvent[] = []
