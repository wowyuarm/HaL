import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { WorkingLog } from "@/components/session/working-log";
import { SessionScopeDialog } from "@/components/session/session-scope-dialog";
import { SessionMountedThreadsDialog } from "@/components/session/session-mounted-threads-dialog";
import { ThreadDetailPanel } from "@/components/thread/thread-detail";
import { ThreadList } from "@/components/thread/thread-list";
import { endSession, submitSessionTurn } from "@/lib/api";
import { isInteractiveSession } from "@/lib/runtime";
import { useHalStore, useLayoutMode } from "@/lib/store";
import { cn } from "@/lib/utils";
import { useSessionSocket } from "@/lib/ws";

// ---------------------------------------------------------------------------
// Grid column definitions per layout mode
// ---------------------------------------------------------------------------

const GRID_NAVIGATION = "grid-cols-[240px_minmax(0,1fr)]";
const GRID_WORKING = "grid-cols-[48px_minmax(0,1fr)]";
const GRID_WORKING_BRIEF = "grid-cols-[48px_minmax(0,1fr)_minmax(340px,420px)]";

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

export default function App() {
  const [scopeDialogOpen, setScopeDialogOpen] = useState(false);
  const [scopeEditorOpen, setScopeEditorOpen] = useState(false);
  const [scopeEditorSessionId, setScopeEditorSessionId] = useState<string | null>(null);

  const layoutMode = useLayoutMode();
  const threads = useHalStore((s) => s.threads);
  const threadDetails = useHalStore((s) => s.threadDetails);
  const sessionManifests = useHalStore((s) => s.sessionManifests);
  const sessionEvents = useHalStore((s) => s.sessionEvents);
  const activeThreadSlug = useHalStore((s) => s.activeThreadSlug);
  const selectedSessionId = useHalStore((s) => s.selectedSessionId);
  const socketState = useHalStore((s) => s.socketState);
  const loadingThreadSlug = useHalStore((s) => s.loadingThreadSlug);
  const loadingSessionId = useHalStore((s) => s.loadingSessionId);
  const creatingSession = useHalStore((s) => s.creatingSession);
  const updatingScopeSessionId = useHalStore((s) => s.updatingScopeSessionId);
  const lastError = useHalStore((s) => s.lastError);
  const briefPanelOpen = useHalStore((s) => s.briefPanelOpen);

  const loadThreads = useHalStore((s) => s.loadThreads);
  const loadThread = useHalStore((s) => s.loadThread);
  const loadSessionEvents = useHalStore((s) => s.loadSessionEvents);
  const applySessionManifest = useHalStore((s) => s.applySessionManifest);
  const selectThread = useHalStore((s) => s.selectThread);
  const selectSession = useHalStore((s) => s.selectSession);
  const createSessionForThread = useHalStore((s) => s.createSessionForThread);
  const createScopedSession = useHalStore((s) => s.createScopedSession);
  const updateSessionScope = useHalStore((s) => s.updateSessionScope);
  const toggleBriefPanel = useHalStore((s) => s.toggleBriefPanel);
  const setError = useHalStore((s) => s.setError);

  // Derived values
  const activeThread = activeThreadSlug ? threadDetails[activeThreadSlug] ?? null : null;
  const selectedSession = selectedSessionId ? sessionManifests[selectedSessionId] ?? null : null;
  const scopeEditorSession = scopeEditorSessionId
    ? sessionManifests[scopeEditorSessionId] ?? null
    : null;
  const loadingThread = Boolean(activeThreadSlug && loadingThreadSlug === activeThreadSlug);
  const loadingSession = Boolean(selectedSessionId && loadingSessionId === selectedSessionId);
  const events = selectedSessionId ? sessionEvents[selectedSessionId] ?? [] : [];
  const latestEventSeq = events.at(-1)?.seq ?? 0;
  const isWorkCanvas = layoutMode === "working" || layoutMode === "review";

  useSessionSocket(
    selectedSession?.session_id ?? null,
    selectedSession?.status ?? null,
  );

  // --- Data loading effects (unchanged) ---

  useEffect(() => {
    void loadThreads();
  }, [loadThreads]);

  useEffect(() => {
    if (!activeThreadSlug) return;
    void loadThread(activeThreadSlug);
  }, [activeThreadSlug, loadThread]);

  useEffect(() => {
    if (!selectedSession) return;
    if (isInteractiveSession(selectedSession.status)) return;
    if (latestEventSeq >= selectedSession.last_event_seq) return;
    void loadSessionEvents(selectedSession.session_id);
  }, [
    latestEventSeq,
    loadSessionEvents,
    selectedSession?.last_event_seq,
    selectedSession?.session_id,
    selectedSession?.status,
  ]);

  // --- Event handlers (unchanged) ---

  const handleSelectThread = (slug: string) => {
    setError(null);
    selectThread(slug);
  };

  const handleSelectSession = (sessionId: string) => {
    setError(null);
    selectSession(sessionId);
  };

  const handleCreateSession = async () => {
    if (!activeThreadSlug) return;
    setError(null);
    await createSessionForThread(activeThreadSlug);
  };

  const handleCreateScopedSession = async (input: {
    primaryThread: string;
    mountedThreads: string[];
  }) => {
    setError(null);
    const manifest = await createScopedSession(input);
    if (manifest) {
      setScopeDialogOpen(false);
    }
  };

  const closeScopeEditor = () => {
    if (updatingScopeSessionId) return;
    setScopeEditorOpen(false);
    setScopeEditorSessionId(null);
  };

  const handleOpenScopeEditor = () => {
    if (!selectedSession) return;
    setError(null);
    setScopeEditorSessionId(selectedSession.session_id);
    setScopeEditorOpen(true);
  };

  const handleUpdateScope = async (input: {
    addThreads: string[];
    removeThreads: string[];
  }) => {
    if (!scopeEditorSession) return;
    const hasChanges = input.addThreads.length > 0 || input.removeThreads.length > 0;
    if (!hasChanges) {
      closeScopeEditor();
      return;
    }
    setError(null);
    const manifest = await updateSessionScope(scopeEditorSession.session_id, input);
    if (manifest) {
      closeScopeEditor();
    }
  };

  const handleSend = async (content: string) => {
    if (!selectedSession) {
      return;
    }
    setError(null);
    try {
      const submission = await submitSessionTurn(selectedSession.session_id, { content });
      if (socketState !== "live") {
        applySessionManifest(submission.session);
        await loadSessionEvents(selectedSession.session_id);
      }
    } catch (error) {
      setError(error instanceof Error ? error.message : "Failed to submit turn.");
    }
  };

  const handleBrief = async () => {
    if (!selectedSession) {
      return;
    }
    setError(null);
    try {
      const manifest = await endSession(selectedSession.session_id, { reason: "brief" });
      if (socketState !== "live") {
        applySessionManifest(manifest);
        await loadSessionEvents(selectedSession.session_id);
      }
    } catch (error) {
      setError(error instanceof Error ? error.message : "Failed to start briefing.");
    }
  };

  const handleDrop = async () => {
    if (!selectedSession) {
      return;
    }
    setError(null);
    try {
      const manifest = await endSession(selectedSession.session_id, { reason: "drop" });
      if (socketState !== "live") {
        applySessionManifest(manifest);
        await loadSessionEvents(selectedSession.session_id);
      }
    } catch (error) {
      setError(error instanceof Error ? error.message : "Failed to drop session.");
    }
  };

  // --- Grid column class ---

  const gridClass = layoutMode === "navigation"
    ? GRID_NAVIGATION
    : isWorkCanvas && briefPanelOpen
      ? GRID_WORKING_BRIEF
      : GRID_WORKING;

  // --- Render ---

  return (
    <div className={cn("grid h-screen bg-hal-canvas text-hal-primary", gridClass)}>
      {/* ── Sidebar ── */}
      {layoutMode === "navigation" ? (
        <NavigationSidebar
          threads={threads}
          activeThreadSlug={activeThreadSlug}
          creatingSession={creatingSession}
          onSelectThread={handleSelectThread}
          onOpenScopeDialog={() => setScopeDialogOpen(true)}
        />
      ) : (
        <ThreadRail
          threads={threads}
          activeThreadSlug={activeThreadSlug}
          creatingSession={creatingSession}
          onSelectThread={handleSelectThread}
          onOpenScopeDialog={() => setScopeDialogOpen(true)}
        />
      )}

      {/* ── Main area ── */}
      <main className="min-w-0 bg-hal-canvas">
        <div
          className={cn(
            "h-full min-h-0",
            isWorkCanvas ? "px-4 py-4" : "px-6 py-6",
          )}
        >
          {isWorkCanvas ? (
            <WorkingLog
              session={selectedSession}
              threadName={activeThread?.name ?? null}
              events={events}
              socketState={socketState}
              scopeEditable={threads.length > 0}
              loading={loadingThread || loadingSession}
              error={lastError}
              briefPanelOpen={briefPanelOpen}
              onSend={handleSend}
              onEditScope={handleOpenScopeEditor}
              onBrief={handleBrief}
              onDrop={handleDrop}
              onToggleBriefPanel={toggleBriefPanel}
            />
          ) : (
            <ThreadDetailPanel
              thread={activeThread}
              selectedSessionId={selectedSessionId}
              onSelectSession={handleSelectSession}
              onCreateSession={handleCreateSession}
              creatingSession={creatingSession}
            />
          )}
        </div>
      </main>

      {/* ── BRIEF panel (Working/Review only, toggled) ── */}
      {isWorkCanvas && briefPanelOpen && (
        <BriefPanel briefMarkdown={activeThread?.brief_markdown ?? null} />
      )}

      {/* ── Dialogs (fixed-position overlays, grid-inert) ── */}
      <SessionScopeDialog
        open={scopeDialogOpen}
        threads={threads}
        initialPrimarySlug={activeThreadSlug}
        creating={creatingSession}
        onClose={() => setScopeDialogOpen(false)}
        onSubmit={handleCreateScopedSession}
      />
      <SessionMountedThreadsDialog
        open={scopeEditorOpen}
        session={scopeEditorSession}
        threads={threads}
        submitting={updatingScopeSessionId === scopeEditorSessionId}
        onClose={closeScopeEditor}
        onSubmit={handleUpdateScope}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Navigation sidebar — full thread list (~240px)
// ---------------------------------------------------------------------------

function NavigationSidebar({
  threads,
  activeThreadSlug,
  creatingSession,
  onSelectThread,
  onOpenScopeDialog,
}: {
  threads: ReturnType<typeof useHalStore.getState>["threads"];
  activeThreadSlug: string | null;
  creatingSession: boolean;
  onSelectThread: (slug: string) => void;
  onOpenScopeDialog: () => void;
}) {
  return (
    <aside className="flex min-h-0 flex-col border-r border-subtle bg-hal-panel">
      <div className="flex-1 overflow-y-auto px-3 py-4">
        <div className="flex items-center justify-between gap-2 px-2">
          <p className="text-xs font-medium uppercase tracking-widest text-hal-muted">Threads</p>
          <button
            type="button"
            onClick={onOpenScopeDialog}
            disabled={threads.length === 0 || creatingSession}
            className="rounded-md border border-border bg-hal-float px-2.5 py-1 text-caption uppercase tracking-wide text-hal-primary transition-colors duration-fast ease-standard hover:bg-hal-canvas disabled:cursor-not-allowed disabled:opacity-50"
          >
            Scope
          </button>
        </div>
        <div className="mt-3">
          <ThreadList
            threads={threads}
            activeThread={activeThreadSlug}
            onSelect={onSelectThread}
          />
        </div>
      </div>
      <div className="border-t border-subtle px-3 py-4">
        <p className="px-2 text-caption uppercase tracking-widest text-hal-muted">Workspace</p>
        <p className="px-2 pt-2 text-meta leading-relaxed text-hal-muted">
          Threads hold durable memory. Sessions are the observable runs beneath them.
        </p>
      </div>
    </aside>
  );
}

// ---------------------------------------------------------------------------
// Thread rail — collapsed icon-only sidebar (~48px)
// ---------------------------------------------------------------------------

function ThreadRail({
  threads,
  activeThreadSlug,
  creatingSession,
  onSelectThread,
  onOpenScopeDialog,
}: {
  threads: ReturnType<typeof useHalStore.getState>["threads"];
  activeThreadSlug: string | null;
  creatingSession: boolean;
  onSelectThread: (slug: string) => void;
  onOpenScopeDialog: () => void;
}) {
  return (
    <aside className="flex min-h-0 flex-col items-center border-r border-subtle bg-hal-canvas">
      <div className="flex flex-1 flex-col items-center gap-1.5 overflow-y-auto py-3">
        {threads.map((thread) => {
          const isActive = thread.slug === activeThreadSlug;
          return (
            <button
              key={thread.slug}
              type="button"
              onClick={() => onSelectThread(thread.slug)}
              title={thread.name}
              aria-label={thread.name}
              className={cn(
                "flex h-8 w-8 shrink-0 items-center justify-center rounded-md border text-caption uppercase",
                "transition-colors duration-normal ease-standard",
                isActive
                  ? "border-accent bg-hal-float text-hal-primary"
                  : "border-subtle bg-hal-canvas text-hal-muted hover:border-border hover:bg-hal-float hover:text-hal-primary",
              )}
            >
              {threadInitial(thread.name)}
            </button>
          );
        })}
      </div>
      <div className="border-t border-subtle p-2">
        <button
          type="button"
          onClick={onOpenScopeDialog}
          disabled={threads.length === 0 || creatingSession}
          title="Create scoped session"
          aria-label="Create scoped session"
          className="flex h-8 w-8 items-center justify-center rounded-md border border-subtle bg-hal-float text-caption text-hal-muted transition-colors duration-normal ease-standard hover:border-border hover:text-hal-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          +
        </button>
      </div>
    </aside>
  );
}

// ---------------------------------------------------------------------------
// BRIEF side panel — thread brief_markdown in an elevated container
// ---------------------------------------------------------------------------

function BriefPanel({ briefMarkdown }: { briefMarkdown: string | null }) {
  return (
    <aside className="min-h-0 border-l border-subtle px-3 py-4">
      <div className="flex h-full min-h-0 flex-col rounded-lg border border-border bg-hal-float shadow-popover">
        <div className="flex h-12 shrink-0 items-center border-b border-subtle px-4">
          <h2 className="text-caption uppercase tracking-widest text-hal-muted">Brief</h2>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
          <div className="prose prose-mineral max-w-none text-[15px] leading-7">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {briefMarkdown || "_This thread does not have a brief yet._"}
            </ReactMarkdown>
          </div>
        </div>
      </div>
    </aside>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Extract the first meaningful character from a thread name for the rail badge. */
function threadInitial(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return "?";
  return trimmed[0]?.toUpperCase() ?? "?";
}
