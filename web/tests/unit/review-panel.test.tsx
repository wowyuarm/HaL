import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'

import { ReviewPanel } from '@/components/session/review-panel'
import { useHalStore } from '@/lib/store'

vi.mock('@/lib/api', () => ({
  getThreadEpisode: vi.fn(),
}))

const { getThreadEpisode } = await import('@/lib/api')

const INITIAL_STATE = useHalStore.getState()

function resetStore(): void {
  useHalStore.setState({
    ...INITIAL_STATE,
    threads: [],
    threadDetails: {},
    sessionManifests: {},
    sessionEvents: {},
    activeThreadSlug: null,
    selectedSessionId: null,
    reviewPanel: null,
    socketState: 'disconnected',
    loadingThreads: false,
    loadingThreadSlug: null,
    loadingSessionId: null,
    creatingSession: false,
    updatingScopeSessionId: null,
    mutatingArchiveSessionId: null,
    showArchived: false,
    activeThreadRequestId: 0,
    lastError: null,
  })
}

describe('ReviewPanel', () => {
  afterEach(() => {
    cleanup()
    resetStore()
    vi.clearAllMocks()
  })

  it('loads and renders episode markdown for episode review panels', async () => {
    vi.mocked(getThreadEpisode).mockResolvedValue({
      thread_slug: 'alpha',
      episode_rel_path: 'episodes/one.md',
      episode_title: 'one',
      markdown: '# Episode one\n\nBody copy.',
    })

    useHalStore.setState({
      reviewPanel: {
        kind: 'episode',
        threadSlug: 'alpha',
        episodePath: 'episodes/one.md',
        episodeTitle: 'one',
      },
    })

    render(<ReviewPanel briefMarkdown={null} threadSlug="alpha" />)

    expect(screen.getByText('Loading episode preview...')).toBeInTheDocument()

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Episode one' })).toBeInTheDocument(),
    )
    expect(getThreadEpisode).toHaveBeenCalledWith('alpha', 'episodes/one.md')
    expect(screen.getByText('Body copy.')).toBeInTheDocument()
  })

  it('shows an error state when episode loading fails', async () => {
    vi.mocked(getThreadEpisode).mockRejectedValue(new Error('boom'))

    useHalStore.setState({
      reviewPanel: {
        kind: 'episode',
        threadSlug: 'alpha',
        episodePath: 'episodes/missing.md',
        episodeTitle: 'missing',
      },
    })

    render(<ReviewPanel briefMarkdown={null} threadSlug="alpha" />)

    await waitFor(() =>
      expect(screen.getByText('Episode could not be loaded.')).toBeInTheDocument(),
    )
    expect(screen.getByText('boom')).toBeInTheDocument()
  })
})
