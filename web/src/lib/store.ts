import { create } from "zustand";

import {
  createSession,
  getSessionEvents,
  getThread,
  listThreads,
  updateSessionScope,
} from "@/lib/api";
import type {
  LayoutMode,
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
  briefPanelOpen: boolean;
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
  setSocketState: (state: SocketState) => void;
  setError: (message: string | null) => void;

  loadThreads: () => Promise<void>;
  loadThread: (
    slug: string,
    options?: { adoptSelection?: boolean; focusSessionId?: string | null },
  ) => Promise<void>;
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
  applySessionManifest: (manifest: SessionManifest) => void;
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

function sessionScopeSlugs(manifest: SessionManifest): string[] {
  const slugs = new Set<string>(manifest.mounted_threads);
  if (manifest.primary_thread) {
    slugs.add(manifest.primary_thread);
  }
  return [...slugs].sort();
}

/** Derive layout mode from current selection state. Pure, no store dependency. */
export function deriveLayoutMode(
  selectedSessionId: string | null,
  sessionManifest: SessionManifest | null,
): LayoutMode {
  if (!selectedSessionId || !sessionManifest) return "navigation";
  if (sessionManifest.status === "active" || sessionManifest.status === "briefing")
    return "working";
  return "review";
}

let nextThreadLoadRequestId = 0;

export const useHalStore = create<HalStore>((set, get) => ({
  threads: [],
  threadDetails: {},
  sessionManifests: {},
  sessionEvents: {},
  activeThreadSlug: null,
  selectedSessionId: null,
  briefPanelOpen: false,
  socketState: "disconnected",
  loadingThreads: false,
  loadingThreadSlug: null,
  loadingSessionId: null,
  creatingSession: false,
  updatingScopeSessionId: null,
  activeThreadRequestId: 0,
  lastError: null,

  selectThread: (slug) => set({ activeThreadSlug: slug, selectedSessionId: null }),
  selectSession: (sessionId) => set({ selectedSessionId: sessionId }),
  toggleBriefPanel: () => set((state) => ({ briefPanelOpen: !state.briefPanelOpen })),
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
            : selectedStillExists
              ? state.selectedSessionId
              : (detail.sessions[0]?.session_id ?? null);
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

  createScopedSession: async ({ primaryThread, mountedThreads }) => {
    set({ creatingSession: true, lastError: null });
    try {
      const manifest = await createSession({
        primary_thread: primaryThread,
        mounted_threads: mountedThreads,
      });
      set((state) => ({
        ...mergeManifestIntoState(state, manifest),
      }));
      await get().loadThreads();
      const activeThreadSlug = get().activeThreadSlug;
      await Promise.all(
        sessionScopeSlugs(manifest).map(async (slug) => {
          await get().loadThread(slug, {
            adoptSelection: slug === activeThreadSlug,
            focusSessionId:
              slug === primaryThread && activeThreadSlug === primaryThread
                ? manifest.session_id
                : null,
          });
        }),
      );
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
      return {
        sessionEvents,
        ...mergeManifestIntoState(state, manifest),
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
      return {
        sessionEvents,
        ...(patchedManifest ? mergeManifestIntoState(state, patchedManifest) : {}),
      };
    }),
}));

// ---------------------------------------------------------------------------
// Derived selector hooks
// ---------------------------------------------------------------------------

/** Derived layout mode — recomputes only when selection or manifest status changes. */
export function useLayoutMode(): LayoutMode {
  return useHalStore((s) => {
    const manifest = s.selectedSessionId
      ? s.sessionManifests[s.selectedSessionId]
      : null;
    return deriveLayoutMode(s.selectedSessionId, manifest ?? null);
  });
}

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
