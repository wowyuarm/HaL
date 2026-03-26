import { useEffect, useState } from 'react'

import { ReadingPanel } from '@/components/layout/reading-panel'
import { HalMarkdown } from '@/components/ui/hal-markdown'
import { getThreadEpisode } from '@/lib/api'
import { useHalStore } from '@/lib/store'
import type { ThreadEpisode } from '@/lib/types'

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
  if (reviewPanel.kind === 'process') return null

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

  return null
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
