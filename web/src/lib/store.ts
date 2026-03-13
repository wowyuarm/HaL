import { create } from "zustand";

import {
  createSession,
  getSessionEvents,
  getThread,
  listThreads,
  updateSessionScope,
} from "@/lib/api";
import type {
  SessionEvent,
  SessionManifest,
  SessionStatus,
  SocketState,
  ThreadDetail,
  ThreadSummary,
} from "@/lib/types";

interface HalStore {
  threads: ThreadSummary[];
  threadDetails: Record<string, ThreadDetail>;
  sessionManifests: Record<string, SessionManifest>;
  sessionEvents: Record<string, SessionEvent[]>;
  activeThreadSlug: string | null;
  selectedSessionId: string | null;
  socketState: SocketState;
  loadingThreads: boolean;
  loadingThread: boolean;
  loadingSession: boolean;
  creatingSession: boolean;
  updatingScopeSessionId: string | null;
  lastError: string | null;

  selectThread: (slug: string) => void;
  selectSession: (sessionId: string | null) => void;
  setSocketState: (state: SocketState) => void;
  setError: (message: string | null) => void;

  loadThreads: () => Promise<void>;
  loadThread: (slug: string) => Promise<void>;
  refreshActiveThread: () => Promise<void>;
  createScopedSession: (input: {
    primaryThread: string;
    mountedThreads?: string[];
  }) => Promise<SessionManifest | null>;
  createSessionForThread: (slug: string) => Promise<SessionManifest | null>;
  updateSessionScope: (
    sessionId: string,
    input: { addThreads?: string[]; removeThreads?: string[] },
  ) => Promise<SessionManifest | null>;
  loadSessionEvents: (sessionId: string) => Promise<void>;
  applySessionSnapshot: (manifest: SessionManifest, events: SessionEvent[]) => void;
  appendSessionEvent: (event: SessionEvent) => void;
}

function mergeSessionEvents(
  current: SessionEvent[] | undefined,
  incoming: SessionEvent[],
): SessionEvent[] {
  const merged = new Map<number, SessionEvent>();
  for (const event of current ?? []) merged.set(event.seq, event);
  for (const event of incoming) merged.set(event.seq, event);
  return [...merged.values()].sort((a, b) => a.seq - b.seq);
}

function upsertManifest(
  manifests: Record<string, SessionManifest>,
  manifest: SessionManifest,
): Record<string, SessionManifest> {
  return { ...manifests, [manifest.session_id]: manifest };
}

function patchManifestFromEvent(
  manifest: SessionManifest | undefined,
  event: SessionEvent,
  options: { alreadySeen: boolean },
): SessionManifest | undefined {
  if (!manifest) return manifest;
  const { alreadySeen } = options;

  const nextManifest: SessionManifest = {
    ...manifest,
    last_event_seq: Math.max(manifest.last_event_seq, event.seq),
  };

  if (!alreadySeen && event.type === "turn.started") {
    nextManifest.turn_count += 1;
  }

  if (event.type === "brief.started") {
    return { ...nextManifest, status: "briefing" };
  }

  if (event.type === "session.scope_updated") {
    const mountedThreads = Array.isArray(event.refs.mounted_threads)
      ? event.refs.mounted_threads.filter((item): item is string => typeof item === "string")
      : nextManifest.mounted_threads;
    return { ...nextManifest, mounted_threads: mountedThreads };
  }

  if (event.type === "session.ended") {
    const reason = typeof event.payload.reason === "string" ? event.payload.reason : "";
    const status: SessionStatus = reason === "user_drop" ? "dropped" : "ended";
    return { ...nextManifest, status, ended_at: event.ts };
  }

  return nextManifest;
}

function sessionBelongsToThread(manifest: SessionManifest, slug: string): boolean {
  return (
    manifest.primary_thread === slug ||
    manifest.mounted_threads.includes(slug) ||
    manifest.touched_threads.includes(slug)
  );
}

function reconcileManifestInThreadDetails(
  details: Record<string, ThreadDetail>,
  manifest: SessionManifest,
): Record<string, ThreadDetail> {
  const nextDetails: Record<string, ThreadDetail> = {};
  for (const [slug, detail] of Object.entries(details)) {
    const hasSession = detail.sessions.some((session) => session.session_id === manifest.session_id);
    const shouldInclude = sessionBelongsToThread(manifest, slug);

    if (!hasSession && !shouldInclude) {
      nextDetails[slug] = detail;
      continue;
    }

    const sessions = (
      shouldInclude
        ? hasSession
          ? detail.sessions.map((session) =>
              session.session_id === manifest.session_id ? manifest : session,
            )
          : [manifest, ...detail.sessions]
        : detail.sessions.filter((session) => session.session_id !== manifest.session_id)
    ).sort((a, b) => b.created_at.localeCompare(a.created_at));

    nextDetails[slug] = {
      ...detail,
      sessions,
      session_counts: countSessions(sessions),
    };
  }
  return nextDetails;
}

function adjustSessionCount(
  counts: Partial<Record<SessionStatus, number>>,
  status: SessionStatus,
  delta: number,
): Partial<Record<SessionStatus, number>> {
  const nextCounts = { ...counts };
  const nextValue = Math.max((nextCounts[status] ?? 0) + delta, 0);
  if (nextValue > 0) {
    nextCounts[status] = nextValue;
  } else {
    delete nextCounts[status];
  }
  return nextCounts;
}

function reconcileManifestInThreadSummaries(
  threads: ThreadSummary[],
  previousManifest: SessionManifest | undefined,
  nextManifest: SessionManifest,
): ThreadSummary[] {
  return threads.map((thread) => {
    const belongedBefore = previousManifest
      ? sessionBelongsToThread(previousManifest, thread.slug)
      : false;
    const belongsNow = sessionBelongsToThread(nextManifest, thread.slug);

    if (!belongedBefore && !belongsNow) return thread;

    let sessionCounts = thread.session_counts;
    if (belongedBefore && previousManifest) {
      sessionCounts = adjustSessionCount(sessionCounts, previousManifest.status, -1);
    }
    if (belongsNow) {
      sessionCounts = adjustSessionCount(sessionCounts, nextManifest.status, 1);
    }

    return {
      ...thread,
      session_counts: sessionCounts,
    };
  });
}

function countSessions(sessions: SessionManifest[]): Partial<Record<SessionStatus, number>> {
  const counts: Partial<Record<SessionStatus, number>> = {};
  for (const session of sessions) {
    counts[session.status] = (counts[session.status] ?? 0) + 1;
  }
  return counts;
}

function syncThreadSummaries(
  threads: ThreadSummary[],
  details: Record<string, ThreadDetail>,
): ThreadSummary[] {
  return threads.map((thread) => {
    const detail = details[thread.slug];
    return detail
      ? {
          ...thread,
          session_counts: detail.session_counts,
          updated_at: detail.updated_at,
        }
      : thread;
  });
}

function normalizeThreadDetail(detail: ThreadDetail): ThreadDetail {
  return {
    ...detail,
    sessions: [...detail.sessions].sort((a, b) => b.created_at.localeCompare(a.created_at)),
  };
}

export const useHalStore = create<HalStore>((set, get) => ({
  threads: [],
  threadDetails: {},
  sessionManifests: {},
  sessionEvents: {},
  activeThreadSlug: null,
  selectedSessionId: null,
  socketState: "disconnected",
  loadingThreads: false,
  loadingThread: false,
  loadingSession: false,
  creatingSession: false,
  updatingScopeSessionId: null,
  lastError: null,

  selectThread: (slug) => set({ activeThreadSlug: slug, selectedSessionId: null }),
  selectSession: (sessionId) => set({ selectedSessionId: sessionId }),
  setSocketState: (state) => set({ socketState: state }),
  setError: (message) => set({ lastError: message }),

  loadThreads: async () => {
    set({ loadingThreads: true, lastError: null });
    try {
      const threads = await listThreads();
      set((state) => ({
        threads,
        activeThreadSlug:
          state.activeThreadSlug && threads.some((thread) => thread.slug === state.activeThreadSlug)
            ? state.activeThreadSlug
            : (threads[0]?.slug ?? null),
        loadingThreads: false,
      }));
    } catch (error) {
      set({
        loadingThreads: false,
        lastError: error instanceof Error ? error.message : "Failed to load threads.",
      });
    }
  },

  loadThread: async (slug) => {
    set({ loadingThread: true, lastError: null });
    try {
      const detail = normalizeThreadDetail(await getThread(slug));
      set((state) => {
        const manifests = { ...state.sessionManifests };
        for (const session of detail.sessions) manifests[session.session_id] = session;

        const nextDetails = { ...state.threadDetails, [slug]: detail };
        const nextThreads = syncThreadSummaries(state.threads, nextDetails);
        const selectedStillExists =
          state.selectedSessionId &&
          detail.sessions.some((session) => session.session_id === state.selectedSessionId);

        return {
          threadDetails: nextDetails,
          sessionManifests: manifests,
          threads: nextThreads,
          activeThreadSlug: slug,
          selectedSessionId: selectedStillExists
            ? state.selectedSessionId
            : (detail.sessions[0]?.session_id ?? null),
          loadingThread: false,
        };
      });
    } catch (error) {
      set({
        loadingThread: false,
        lastError: error instanceof Error ? error.message : `Failed to load thread ${slug}.`,
      });
    }
  },

  refreshActiveThread: async () => {
    const slug = get().activeThreadSlug;
    if (!slug) return;
    await get().loadThread(slug);
  },

  createScopedSession: async ({ primaryThread, mountedThreads }) => {
    set({ creatingSession: true, lastError: null });
    try {
      const manifest = await createSession({
        primary_thread: primaryThread,
        mounted_threads: mountedThreads,
      });
      set((state) => ({
        sessionManifests: upsertManifest(state.sessionManifests, manifest),
      }));
      await get().loadThreads();
      await get().loadThread(primaryThread);
      set({ selectedSessionId: manifest.session_id, creatingSession: false });
      return manifest;
    } catch (error) {
      set({
        creatingSession: false,
        lastError: error instanceof Error ? error.message : "Failed to create session.",
      });
      return null;
    }
  },

  createSessionForThread: async (slug) => {
    return await get().createScopedSession({ primaryThread: slug });
  },

  updateSessionScope: async (sessionId, { addThreads, removeThreads }) => {
    set({ updatingScopeSessionId: sessionId, lastError: null });
    try {
      const manifest = await updateSessionScope(sessionId, {
        add_threads: addThreads,
        remove_threads: removeThreads,
      });
      set((state) => {
        const previousManifest = state.sessionManifests[manifest.session_id];
        const sessionManifests = upsertManifest(state.sessionManifests, manifest);
        const baseThreads = reconcileManifestInThreadSummaries(
          state.threads,
          previousManifest,
          manifest,
        );
        const threadDetails = reconcileManifestInThreadDetails(state.threadDetails, manifest);
        return {
          sessionManifests,
          threadDetails,
          threads: syncThreadSummaries(baseThreads, threadDetails),
          updatingScopeSessionId: null,
        };
      });
      return manifest;
    } catch (error) {
      set({
        updatingScopeSessionId: null,
        lastError: error instanceof Error ? error.message : "Failed to update session scope.",
      });
      return null;
    }
  },

  loadSessionEvents: async (sessionId) => {
    set({ loadingSession: true, lastError: null });
    try {
      const events = await getSessionEvents(sessionId);
      set((state) => ({
        sessionEvents: { ...state.sessionEvents, [sessionId]: events },
        loadingSession: false,
      }));
    } catch (error) {
      set({
        loadingSession: false,
        lastError: error instanceof Error ? error.message : "Failed to load session events.",
      });
    }
  },

  applySessionSnapshot: (manifest, events) =>
    set((state) => {
      const previousManifest = state.sessionManifests[manifest.session_id];
      const sessionEvents = {
        ...state.sessionEvents,
        [manifest.session_id]: [...events].sort((a, b) => a.seq - b.seq),
      };
      const sessionManifests = upsertManifest(state.sessionManifests, manifest);
      const baseThreads = reconcileManifestInThreadSummaries(
        state.threads,
        previousManifest,
        manifest,
      );
      const threadDetails = reconcileManifestInThreadDetails(state.threadDetails, manifest);
      return {
        sessionEvents,
        sessionManifests,
        threadDetails,
        threads: syncThreadSummaries(baseThreads, threadDetails),
        selectedSessionId: manifest.session_id,
      };
    }),

  appendSessionEvent: (event) =>
    set((state) => {
      const currentEvents = state.sessionEvents[event.session_id] ?? [];
      const alreadySeen = currentEvents.some((existing) => existing.seq === event.seq);
      const currentManifest = state.sessionManifests[event.session_id];
      const patchedManifest = patchManifestFromEvent(currentManifest, event, { alreadySeen });
      const sessionEvents = {
        ...state.sessionEvents,
        [event.session_id]: mergeSessionEvents(currentEvents, [event]),
      };
      const sessionManifests = patchedManifest
        ? upsertManifest(state.sessionManifests, patchedManifest)
        : state.sessionManifests;
      const baseThreads = patchedManifest
        ? reconcileManifestInThreadSummaries(state.threads, currentManifest, patchedManifest)
        : state.threads;
      const threadDetails = patchedManifest
        ? reconcileManifestInThreadDetails(state.threadDetails, patchedManifest)
        : state.threadDetails;
      return {
        sessionEvents,
        sessionManifests,
        threadDetails,
        threads: syncThreadSummaries(baseThreads, threadDetails),
      };
    }),
}));
