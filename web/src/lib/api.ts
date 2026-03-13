import type { SessionEvent, SessionManifest, ThreadDetail, ThreadSummary } from "@/lib/types";

async function requestJson<T>(input: string, init?: RequestInit): Promise<T> {
  const response = await fetch(input, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

export async function listThreads(): Promise<ThreadSummary[]> {
  const payload = await requestJson<{ threads: ThreadSummary[] }>("/threads");
  return payload.threads;
}

export async function getThread(slug: string): Promise<ThreadDetail> {
  const payload = await requestJson<{ thread: ThreadDetail }>(
    `/threads/${encodeURIComponent(slug)}`,
  );
  return payload.thread;
}

export async function createSession(input: {
  primary_thread?: string | null;
  mounted_threads?: string[];
}): Promise<SessionManifest> {
  const payload = await requestJson<{ session: SessionManifest }>("/sessions", {
    method: "POST",
    body: JSON.stringify(input),
  });
  return payload.session;
}

export async function getSessionEvents(sessionId: string): Promise<SessionEvent[]> {
  const payload = await requestJson<{ events: SessionEvent[] }>(
    `/sessions/${encodeURIComponent(sessionId)}/events`,
  );
  return payload.events;
}

export async function updateSessionScope(
  sessionId: string,
  input: { add_threads?: string[]; remove_threads?: string[] },
): Promise<SessionManifest> {
  const payload = await requestJson<{ session: SessionManifest }>(
    `/sessions/${encodeURIComponent(sessionId)}/scope`,
    {
      method: "POST",
      body: JSON.stringify(input),
    },
  );
  return payload.session;
}
