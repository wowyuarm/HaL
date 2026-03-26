import type {
  SessionEvent,
  SessionManifest,
  ThreadDetail,
  ThreadEpisode,
  ThreadSummary,
  WebAttachmentInput,
} from '@/lib/types'

export interface SessionTurnSubmission {
  session: SessionManifest
  delivery: 'turn_started' | 'intervention_queued'
}

async function requestJson<T>(input: string, init?: RequestInit): Promise<T> {
  const response = await fetch(input, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  })
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `${response.status} ${response.statusText}`)
  }
  return (await response.json()) as T
}

export async function listThreads(): Promise<ThreadSummary[]> {
  const payload = await requestJson<{ threads: ThreadSummary[] }>('/threads')
  return payload.threads
}

export async function getThread(
  slug: string,
  input?: { includeArchived?: boolean },
): Promise<ThreadDetail> {
  const params = new URLSearchParams()
  if (input?.includeArchived) params.set('include_archived', 'true')
  const query = params.toString()
  const payload = await requestJson<{ thread: ThreadDetail }>(
    `/threads/${encodeURIComponent(slug)}${query ? `?${query}` : ''}`,
  )
  return payload.thread
}

export async function createSession(input: {
  primary_thread?: string | null
  mounted_threads?: string[]
}): Promise<SessionManifest> {
  const payload = await requestJson<{ session: SessionManifest }>('/sessions', {
    method: 'POST',
    body: JSON.stringify(input),
  })
  return payload.session
}

export async function updateSessionTitle(
  sessionId: string,
  input: { title: string | null },
): Promise<SessionManifest> {
  const payload = await requestJson<{ session: SessionManifest }>(
    `/sessions/${encodeURIComponent(sessionId)}/title`,
    {
      method: 'POST',
      body: JSON.stringify(input),
    },
  )
  return payload.session
}

export async function archiveSession(sessionId: string): Promise<SessionManifest> {
  const payload = await requestJson<{ session: SessionManifest }>(
    `/sessions/${encodeURIComponent(sessionId)}/archive`,
    {
      method: 'POST',
      body: JSON.stringify({}),
    },
  )
  return payload.session
}

export async function restoreSession(sessionId: string): Promise<SessionManifest> {
  const payload = await requestJson<{ session: SessionManifest }>(
    `/sessions/${encodeURIComponent(sessionId)}/restore`,
    {
      method: 'POST',
      body: JSON.stringify({}),
    },
  )
  return payload.session
}

export async function submitSessionTurn(
  sessionId: string,
  input: { content: string; attachments?: WebAttachmentInput[] },
): Promise<SessionTurnSubmission> {
  return await requestJson<SessionTurnSubmission>(
    `/sessions/${encodeURIComponent(sessionId)}/turns`,
    {
      method: 'POST',
      body: JSON.stringify(input),
    },
  )
}

export async function getSessionEvents(sessionId: string): Promise<SessionEvent[]> {
  const payload = await requestJson<{ events: SessionEvent[] }>(
    `/sessions/${encodeURIComponent(sessionId)}/events`,
  )
  return payload.events
}

export async function getThreadEpisode(
  threadSlug: string,
  episodePath: string,
): Promise<ThreadEpisode> {
  const payload = await requestJson<{ episode: ThreadEpisode }>(
    `/threads/${encodeURIComponent(threadSlug)}/episode/${encodeURIComponent(episodePath)}`,
  )
  return payload.episode
}

export async function endSession(
  sessionId: string,
  input: { reason: 'brief' | 'drop'; user_prompt?: string },
): Promise<SessionManifest> {
  const payload = await requestJson<{ session: SessionManifest }>(
    `/sessions/${encodeURIComponent(sessionId)}/end`,
    {
      method: 'POST',
      body: JSON.stringify(input),
    },
  )
  return payload.session
}

export async function updateSessionScope(
  sessionId: string,
  input: { add_threads?: string[]; remove_threads?: string[] },
): Promise<SessionManifest> {
  const payload = await requestJson<{ session: SessionManifest }>(
    `/sessions/${encodeURIComponent(sessionId)}/scope`,
    {
      method: 'POST',
      body: JSON.stringify(input),
    },
  )
  return payload.session
}
