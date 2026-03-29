import assert from 'node:assert/strict'

import { useHalStore } from '../../src/lib/store'
import type { SessionManifest, ThreadDetail, ThreadSummary } from '../../src/lib/types'

const INITIAL_STATE = useHalStore.getState()
const ORIGINAL_FETCH = globalThis.fetch

function makeThreadSummary(
  slug: string,
  sessionCounts: ThreadSummary['session_counts'],
  updatedAt: string,
): ThreadSummary {
  return {
    slug,
    name: slug,
    status: 'ready',
    scope: 'thread',
    description: '',
    updated_at: updatedAt,
    session_counts: sessionCounts,
  }
}

function makeSession(input: {
  sessionId: string
  status?: SessionManifest['status']
  createdAt: string
  primaryThread?: string | null
  archivedAt?: string | null
}): SessionManifest {
  return {
    session_id: input.sessionId,
    status: input.status ?? 'active',
    title: input.sessionId,
    created_at: input.createdAt,
    ended_at: null,
    channel: null,
    chat_id: null,
    primary_thread: input.primaryThread ?? 'alpha',
    mounted_threads: [],
    touched_threads: [input.primaryThread ?? 'alpha'],
    turn_count: 0,
    last_event_seq: 0,
    archived_at: input.archivedAt ?? null,
  }
}

function makeThreadDetail(input: {
  slug: string
  updatedAt: string
  sessionCounts: ThreadSummary['session_counts']
  sessions: SessionManifest[]
}): ThreadDetail {
  return {
    ...makeThreadSummary(input.slug, input.sessionCounts, input.updatedAt),
    brief_markdown: '',
    sessions: input.sessions,
    episode_refs: {},
  }
}

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    statusText: 'OK',
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as Response
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((nextResolve) => {
    resolve = nextResolve
  })
  return { promise, resolve }
}

function resetStore(overrides: Partial<ReturnType<typeof useHalStore.getState>> = {}): void {
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
    ...overrides,
  })
}

async function runTest(name: string, fn: () => Promise<void> | void): Promise<void> {
  try {
    resetStore()
    await fn()
    console.log(`PASS ${name}`)
  } catch (error) {
    console.error(`FAIL ${name}`)
    throw error
  } finally {
    globalThis.fetch = ORIGINAL_FETCH
  }
}

await runTest('setShowArchived only flips the flag', () => {
  let loadCount = 0
  resetStore({
    activeThreadSlug: 'alpha',
    loadThread: (async () => {
      loadCount += 1
    }) as typeof INITIAL_STATE.loadThread,
  })

  useHalStore.getState().setShowArchived(true)

  assert.equal(useHalStore.getState().showArchived, true)
  assert.equal(loadCount, 0)
})

await runTest('loadThread ignores stale archived responses', async () => {
  const liveSession = makeSession({
    sessionId: 'live-1',
    createdAt: '2026-03-26T09:00:00Z',
  })
  const archivedSession = makeSession({
    sessionId: 'archived-1',
    status: 'ended',
    createdAt: '2026-03-25T09:00:00Z',
    archivedAt: '2026-03-26T09:30:00Z',
  })
  const liveDetail = makeThreadDetail({
    slug: 'alpha',
    updatedAt: '2026-03-26T09:00:00Z',
    sessionCounts: { active: 1 },
    sessions: [liveSession],
  })
  const archivedDetail = makeThreadDetail({
    slug: 'alpha',
    updatedAt: '2026-03-26T09:30:00Z',
    sessionCounts: { active: 1, ended: 1 },
    sessions: [liveSession, archivedSession],
  })
  const archivedResponse = deferred<Response>()
  const liveResponse = deferred<Response>()

  globalThis.fetch = (async (input) => {
    const url = String(input)
    if (url.includes('include_archived=true')) {
      return await archivedResponse.promise
    }
    if (url === '/threads/alpha') {
      return await liveResponse.promise
    }
    throw new Error(`Unexpected fetch: ${url}`)
  }) as typeof fetch

  resetStore({
    activeThreadSlug: 'alpha',
    showArchived: true,
    threads: [makeThreadSummary('alpha', { active: 1 }, '2026-03-26T09:00:00Z')],
  })

  const archivedLoad = useHalStore.getState().loadThread('alpha')

  useHalStore.setState({ showArchived: false })
  const liveLoad = useHalStore.getState().loadThread('alpha')

  liveResponse.resolve(jsonResponse({ thread: liveDetail }))
  await liveLoad

  archivedResponse.resolve(jsonResponse({ thread: archivedDetail }))
  await archivedLoad

  const detail = useHalStore.getState().threadDetails.alpha
  assert.ok(detail)
  assert.deepEqual(
    detail.sessions.map((session) => session.session_id),
    ['live-1'],
  )
})

await runTest('showArchived keeps sidebar counts and order on summary basis', async () => {
  const liveSession = makeSession({
    sessionId: 'live-1',
    createdAt: '2026-03-26T09:00:00Z',
  })
  const archivedSession = makeSession({
    sessionId: 'archived-1',
    status: 'ended',
    createdAt: '2026-03-25T09:00:00Z',
    archivedAt: '2026-03-26T09:30:00Z',
  })
  const archivedDetail = makeThreadDetail({
    slug: 'alpha',
    updatedAt: '2026-03-26T09:30:00Z',
    sessionCounts: { active: 1, ended: 1 },
    sessions: [liveSession, archivedSession],
  })

  globalThis.fetch = (async (input) => {
    const url = String(input)
    if (url === '/threads/alpha?include_archived=true') {
      return jsonResponse({ thread: archivedDetail })
    }
    throw new Error(`Unexpected fetch: ${url}`)
  }) as typeof fetch

  resetStore({
    activeThreadSlug: 'alpha',
    showArchived: true,
    threads: [
      makeThreadSummary('beta', { active: 2 }, '2026-03-26T10:00:00Z'),
      makeThreadSummary('alpha', { active: 1 }, '2026-03-26T09:00:00Z'),
    ],
  })

  await useHalStore.getState().loadThread('alpha')

  const { threads } = useHalStore.getState()
  assert.deepEqual(
    threads.map((thread) => thread.slug),
    ['beta', 'alpha'],
  )
  assert.deepEqual(threads.find((thread) => thread.slug === 'alpha')?.session_counts, { active: 1 })
})

await runTest(
  'live detail still refreshes sidebar counts when archived sessions are hidden',
  async () => {
    const firstLiveSession = makeSession({
      sessionId: 'live-2',
      createdAt: '2026-03-26T10:00:00Z',
    })
    const secondLiveSession = makeSession({
      sessionId: 'live-1',
      createdAt: '2026-03-26T09:00:00Z',
    })
    const liveDetail = makeThreadDetail({
      slug: 'alpha',
      updatedAt: '2026-03-26T10:00:00Z',
      sessionCounts: { active: 2 },
      sessions: [firstLiveSession, secondLiveSession],
    })

    globalThis.fetch = (async (input) => {
      const url = String(input)
      if (url === '/threads/alpha') {
        return jsonResponse({ thread: liveDetail })
      }
      throw new Error(`Unexpected fetch: ${url}`)
    }) as typeof fetch

    resetStore({
      activeThreadSlug: 'alpha',
      threads: [makeThreadSummary('alpha', { active: 1 }, '2026-03-26T09:00:00Z')],
    })

    await useHalStore.getState().loadThread('alpha')

    assert.deepEqual(useHalStore.getState().threadDetails.alpha?.sessions.length, 2)
    assert.deepEqual(useHalStore.getState().threads[0]?.session_counts, { active: 2 })
  },
)
