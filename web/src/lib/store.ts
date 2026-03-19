import { create } from "zustand";

import {
  createSession,
  getSessionEvents,
  getThread,
  listThreads,
  updateSessionTitle,
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

export type ReviewPanelState =
  | { kind: "brief" }
  | { kind: "evidence"; turnId: string }
  | {
      kind: "episode";
      threadSlug: string;
      episodePath: string;
      episodeTitle?: string | null;
    }
  | null;

interface HalStore {
  threads: ThreadSummary[];
  threadDetails: Record<string, ThreadDetail>;
  sessionManifests: Record<string, SessionManifest>;
  sessionEvents: Record<string, SessionEvent[]>;
  activeThreadSlug: string | null;
  selectedSessionId: string | null;
  reviewPanel: ReviewPanelState;
  socketState: SocketState;
  loadingThreads: boolean;
  loadingThreadSlug: string | null;
  loadingSessionId: string | null;
  creatingSession: boolean;
  updatingScopeSessionId: string | null;
  activeThreadRequestId: number;
  lastError: string | null;

  selectThread: (slug: string) => void;
  selectSession: (sessionId: string | null) => void;
  toggleBriefPanel: () => void;
  closeReviewPanel: () => void;
  openInspector: (turnId: string) => void;
  openEpisode: (input: {
    threadSlug: string;
    episodePath: string;
    episodeTitle?: string | null;
  }) => void;
  setSocketState: (state: SocketState) => void;
  setError: (message: string | null) => void;

  loadThreads: () => Promise<void>;
  loadThread: (
    slug: string,
    options?: { adoptSelection?: boolean; focusSessionId?: string | null },
  ) => Promise<void>;
  refreshActiveThread: () => Promise<void>;
  createSessionForThread: (slug: string) => Promise<SessionManifest | null>;
  updateSessionTitle: (
    sessionId: string,
    input: { title: string | null },
  ) => Promise<SessionManifest | null>;
  updateSessionScope: (
    sessionId: string,
    input: { addThreads?: string[]; removeThreads?: string[] },
  ) => Promise<SessionManifest | null>;
  loadSessionEvents: (sessionId: string) => Promise<void>;
  applySessionManifest: (manifest: SessionManifest) => void;
  applySessionSnapshot: (manifest: SessionManifest, events: SessionEvent[]) => void;
  appendSessionEvent: (event: SessionEvent) => void;
}

function sessionTotalCount(counts: ThreadSummary["session_counts"]): number {
  return (
    (counts.active ?? 0) +
    (counts.briefing ?? 0) +
    (counts.ended ?? 0) +
    (counts.dropped ?? 0)
  );
}

function liveSessionCount(counts: ThreadSummary["session_counts"]): number {
  return (counts.active ?? 0) + (counts.briefing ?? 0);
}

function sortThreadSummaries(threads: ThreadSummary[]): ThreadSummary[] {
  return [...threads].sort((a, b) => {
    const totalDelta = sessionTotalCount(b.session_counts) - sessionTotalCount(a.session_counts);
    if (totalDelta !== 0) return totalDelta;

    const liveDelta = liveSessionCount(b.session_counts) - liveSessionCount(a.session_counts);
    if (liveDelta !== 0) return liveDelta;

    if (a.updated_at && b.updated_at && a.updated_at !== b.updated_at) {
      return b.updated_at.localeCompare(a.updated_at);
    }
    if (a.updated_at && !b.updated_at) return -1;
    if (!a.updated_at && b.updated_at) return 1;
    return a.slug.localeCompare(b.slug);
  });
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
  return manifest.primary_thread === slug || manifest.mounted_threads.includes(slug);
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
  return sortThreadSummaries(
    threads.map((thread) => {
      const detail = details[thread.slug];
      return detail
        ? {
            ...thread,
            session_counts: detail.session_counts,
            updated_at: detail.updated_at,
          }
        : thread;
    }),
  );
}

function normalizeThreadDetail(detail: ThreadDetail): ThreadDetail {
  return {
    ...detail,
    sessions: [...detail.sessions].sort((a, b) => b.created_at.localeCompare(a.created_at)),
  };
}

function mergeManifestIntoState(
  state: Pick<HalStore, "threads" | "threadDetails" | "sessionManifests">,
  manifest: SessionManifest,
): Pick<HalStore, "threads" | "threadDetails" | "sessionManifests"> {
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
  };
}

let nextThreadLoadRequestId = 0;

export const useHalStore = create<HalStore>((set, get) => ({
  threads: [],
  threadDetails: {},
  sessionManifests: {},
  sessionEvents: {},
  activeThreadSlug: null,
  selectedSessionId: null,
  reviewPanel: null,
  socketState: "disconnected",
  loadingThreads: false,
  loadingThreadSlug: null,
  loadingSessionId: null,
  creatingSession: false,
  updatingScopeSessionId: null,
  activeThreadRequestId: 0,
  lastError: null,

  selectThread: (slug) =>
    set(() => ({
      activeThreadSlug: slug,
      selectedSessionId: null,
      reviewPanel: null,
    })),
  selectSession: (sessionId) => set({ selectedSessionId: sessionId, reviewPanel: null }),
  toggleBriefPanel: () =>
    set((state) => ({
      reviewPanel: state.reviewPanel?.kind === "brief" ? null : { kind: "brief" },
    })),
  closeReviewPanel: () => set({ reviewPanel: null }),
  openInspector: (turnId) =>
    set((state) => ({
      reviewPanel:
        state.reviewPanel?.kind === "evidence" && state.reviewPanel.turnId === turnId
          ? null
          : { kind: "evidence", turnId },
    })),
  openEpisode: ({ threadSlug, episodePath, episodeTitle }) =>
    set({
      reviewPanel: {
        kind: "episode",
        threadSlug,
        episodePath,
        episodeTitle,
      },
    }),
  setSocketState: (state) => set({ socketState: state }),
  setError: (message) => set({ lastError: message }),

  loadThreads: async () => {
    set({ loadingThreads: true, lastError: null });
    try {
      const threads = await listThreads();
      set((state) => ({
        threads: sortThreadSummaries(threads),
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

  loadThread: async (slug, options) => {
    const adoptSelection = options?.adoptSelection ?? true;
    const focusSessionId = options?.focusSessionId ?? null;
    const requestId = adoptSelection ? ++nextThreadLoadRequestId : 0;
    if (adoptSelection) {
      set({ loadingThreadSlug: slug, activeThreadRequestId: requestId, lastError: null });
    }
    try {
      const detail = normalizeThreadDetail(await getThread(slug));
      set((state) => {
        const manifests = { ...state.sessionManifests };
        for (const session of detail.sessions) manifests[session.session_id] = session;

        const nextDetails = { ...state.threadDetails, [slug]: detail };
        const nextThreads = syncThreadSummaries(state.threads, nextDetails);
        const nextState: Partial<HalStore> = {
          threadDetails: nextDetails,
          sessionManifests: manifests,
          threads: nextThreads,
        };
        if (
          adoptSelection &&
          state.activeThreadSlug === slug &&
          state.activeThreadRequestId === requestId
        ) {
          const focusExists =
            focusSessionId &&
            detail.sessions.some((session) => session.session_id === focusSessionId);
          const selectedStillExists =
            state.selectedSessionId &&
            detail.sessions.some((session) => session.session_id === state.selectedSessionId);
          nextState.selectedSessionId = focusExists
            ? focusSessionId
            : state.selectedSessionId === null
              ? null
              : selectedStillExists
                ? state.selectedSessionId
                : null;
          if (nextState.selectedSessionId !== state.selectedSessionId) {
            nextState.reviewPanel = null;
          }
          nextState.loadingThreadSlug = null;
        }
        return nextState as Partial<HalStore>;
      });
    } catch (error) {
      if (!adoptSelection) {
        return;
      }
      set((state) =>
        state.activeThreadSlug === slug && state.activeThreadRequestId === requestId
          ? {
              loadingThreadSlug: null,
              lastError: error instanceof Error ? error.message : `Failed to load thread ${slug}.`,
            }
          : {},
      );
    }
  },

  refreshActiveThread: async () => {
    const slug = get().activeThreadSlug;
    if (!slug) return;
    await get().loadThread(slug);
  },

  createSessionForThread: async (slug) => {
    set({ creatingSession: true, lastError: null });
    try {
      const manifest = await createSession({
        primary_thread: slug,
      });
      set((state) => ({
        ...mergeManifestIntoState(state, manifest),
      }));
      await get().loadThreads();
      await get().loadThread(slug, {
        focusSessionId: manifest.session_id,
      });
      set({ creatingSession: false });
      return manifest;
    } catch (error) {
      set({
        creatingSession: false,
        lastError: error instanceof Error ? error.message : "Failed to create session.",
      });
      return null;
    }
  },

  updateSessionTitle: async (sessionId, { title }) => {
    set({ lastError: null });
    try {
      const manifest = await updateSessionTitle(sessionId, { title });
      set((state) => ({
        ...mergeManifestIntoState(state, manifest),
      }));
      return manifest;
    } catch (error) {
      set({
        lastError: error instanceof Error ? error.message : "Failed to update session title.",
      });
      return null;
    }
  },

  updateSessionScope: async (sessionId, { addThreads, removeThreads }) => {
    set({ updatingScopeSessionId: sessionId, lastError: null });
    try {
      const manifest = await updateSessionScope(sessionId, {
        add_threads: addThreads,
        remove_threads: removeThreads,
      });
      set((state) => ({
        ...mergeManifestIntoState(state, manifest),
        updatingScopeSessionId: null,
      }));
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
    set({ loadingSessionId: sessionId, lastError: null });
    try {
      const events = await getSessionEvents(sessionId);
      set((state) =>
        state.loadingSessionId === sessionId
          ? {
              sessionEvents: { ...state.sessionEvents, [sessionId]: events },
              loadingSessionId: null,
            }
          : {
              sessionEvents: { ...state.sessionEvents, [sessionId]: events },
            },
      );
    } catch (error) {
      set((state) =>
        state.loadingSessionId === sessionId
          ? {
              loadingSessionId: null,
              lastError:
                error instanceof Error ? error.message : "Failed to load session events.",
            }
          : {},
      );
    }
  },

  applySessionManifest: (manifest) =>
    set((state) => ({
      ...mergeManifestIntoState(state, manifest),
    })),

  applySessionSnapshot: (manifest, events) =>
    set((state) => {
      const sessionEvents = {
        ...state.sessionEvents,
        [manifest.session_id]: [...events].sort((a, b) => a.seq - b.seq),
      };
      const sessionChanged = state.selectedSessionId !== manifest.session_id;
      return {
        sessionEvents,
        ...mergeManifestIntoState(state, manifest),
        selectedSessionId: manifest.session_id,
        reviewPanel: sessionChanged ? null : state.reviewPanel,
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
      return {
        sessionEvents,
        ...(patchedManifest ? mergeManifestIntoState(state, patchedManifest) : {}),
      };
    }),
}));

// ---------------------------------------------------------------------------
// Derived selector hooks
// ---------------------------------------------------------------------------

/** ThreadDetail for the currently active thread, or null. */
export function useCurrentThread(): ThreadDetail | null {
  return useHalStore((s) =>
    s.activeThreadSlug ? (s.threadDetails[s.activeThreadSlug] ?? null) : null,
  );
}

/** SessionManifest for the currently selected session, or null. */
export function useCurrentSession(): SessionManifest | null {
  return useHalStore((s) =>
    s.selectedSessionId ? (s.sessionManifests[s.selectedSessionId] ?? null) : null,
  );
}

/** Whether the selected session accepts interaction (active or briefing). */
export function useIsInteractive(): boolean {
  return useHalStore((s) => {
    if (!s.selectedSessionId) return false;
    const manifest = s.sessionManifests[s.selectedSessionId];
    return manifest
      ? manifest.status === "active" || manifest.status === "briefing"
      : false;
  });
}
