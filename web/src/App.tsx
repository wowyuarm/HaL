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

const GRID_NAVIGATION = "grid-cols-1 lg:grid-cols-[284px_minmax(0,1fr)]";
const GRID_WORKING = "grid-cols-1 lg:grid-cols-[68px_minmax(0,1fr)]";
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
    if (latestEventSeq >= selectedSession.last_event_seq) return;
    if (isInteractiveSession(selectedSession.status) && socketState === "live") return;
    void loadSessionEvents(selectedSession.session_id);
  }, [
    latestEventSeq,
    loadSessionEvents,
    selectedSession?.last_event_seq,
    selectedSession?.session_id,
    selectedSession?.status,
    socketState,
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

  const gridClass = layoutMode === "navigation" ? GRID_NAVIGATION : GRID_WORKING;

  // --- Render ---

  return (
    <div
      className={cn(
        "relative grid h-screen min-h-screen overflow-hidden bg-hal-canvas text-hal-primary",
        gridClass,
      )}
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 opacity-60 [background-image:repeating-linear-gradient(180deg,transparent_0,transparent_31px,rgba(36,33,29,0.03)_32px)]"
      />

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
      <main className="relative z-10 min-h-0 min-w-0 overflow-hidden bg-transparent">
        <div
          className={cn(
            "h-full min-h-0",
            isWorkCanvas
              ? "px-3 py-3 md:px-4 md:py-4 lg:px-5 lg:py-5"
              : "px-3 py-4 md:px-5 md:py-5 lg:px-7 lg:py-7",
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
      {isWorkCanvas && (
        <BriefPanel
          open={briefPanelOpen}
          briefMarkdown={activeThread?.brief_markdown ?? null}
        />
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
    <aside className="relative z-10 flex min-h-0 flex-col overflow-hidden border-b border-subtle bg-[color:var(--surface-veil)] backdrop-blur-[2px] lg:border-b-0 lg:border-r">
      <div className="flex-1 overflow-y-auto px-3 py-4 md:px-4 lg:px-4">
        <div className="flex items-center justify-between gap-3 px-1">
          <div>
            <p className="hal-rule-label">Threads</p>
            <p className="mt-2 text-meta text-hal-muted">
              Durable collaboration containers and their current surface state.
            </p>
          </div>
          <button
            type="button"
            onClick={onOpenScopeDialog}
            disabled={threads.length === 0 || creatingSession}
            className="rounded-full border border-border bg-hal-float px-3 py-1.5 text-caption font-semibold uppercase tracking-[0.14em] text-hal-primary transition-colors duration-fast ease-standard hover:bg-hal-canvas disabled:cursor-not-allowed disabled:opacity-50"
          >
            Scope
          </button>
        </div>
        <div className="mt-4">
          <ThreadList
            threads={threads}
            activeThread={activeThreadSlug}
            onSelect={onSelectThread}
            className="grid gap-2 md:grid-cols-2 lg:block lg:space-y-1"
          />
        </div>
      </div>
      <div className="hidden border-t border-subtle px-4 py-4 lg:block">
        <p className="hal-meta-kicker">Workspace</p>
        <p className="pt-2 text-meta leading-relaxed text-hal-muted">
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
    <aside className="relative z-10 flex min-h-0 overflow-hidden border-b border-subtle bg-[color:var(--surface-veil)] px-3 py-2 backdrop-blur-[2px] lg:flex-col lg:items-center lg:border-b-0 lg:border-r lg:bg-transparent lg:px-0 lg:py-0 lg:backdrop-blur-0">
      <div className="pr-2 lg:border-b lg:border-subtle lg:px-0 lg:py-3">
        <button
          type="button"
          onClick={onOpenScopeDialog}
          disabled={threads.length === 0 || creatingSession}
          title="Create scoped session"
          aria-label="Create scoped session"
          className="flex h-9 min-w-9 items-center justify-center rounded-full border border-subtle bg-hal-float px-3 text-caption font-semibold uppercase tracking-[0.16em] text-hal-muted transition-colors duration-normal ease-standard hover:border-border hover:text-hal-primary disabled:cursor-not-allowed disabled:opacity-50 lg:h-10 lg:w-10 lg:rounded-xl lg:px-0"
        >
          +
        </button>
      </div>
      <div className="flex min-w-0 flex-1 items-center gap-2 overflow-x-auto pb-1 lg:flex-col lg:items-center lg:gap-2 lg:overflow-y-auto lg:overflow-x-hidden lg:px-0 lg:py-4">
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
                "flex h-9 shrink-0 items-center justify-center gap-2 rounded-full border px-3 text-caption uppercase lg:h-10 lg:w-10 lg:rounded-xl lg:px-0",
                "transition-colors duration-normal ease-standard",
                isActive
                  ? "border-accent bg-hal-float text-hal-primary shadow-sm"
                  : "border-subtle bg-[rgba(255,255,255,0.34)] text-hal-muted hover:border-border hover:bg-hal-float hover:text-hal-primary",
              )}
            >
              <span className="font-mono text-[10px] font-semibold tracking-[0.12em]">
                {threadMonogram(thread.name, thread.slug)}
              </span>
              <span className="max-w-[8rem] truncate text-meta normal-case tracking-normal text-current lg:hidden">
                {thread.name}
              </span>
            </button>
          );
        })}
      </div>
    </aside>
  );
}

// ---------------------------------------------------------------------------
// BRIEF side panel — thread brief_markdown in an elevated container
// ---------------------------------------------------------------------------

function BriefPanel({
  open,
  briefMarkdown,
}: {
  open: boolean;
  briefMarkdown: string | null;
}) {
  return (
    <aside
      className={cn(
        "absolute inset-y-0 right-0 z-20 hidden w-[min(440px,36vw)] px-3 py-5 transition-all duration-normal ease-standard lg:block",
        open
          ? "pointer-events-auto translate-x-0 opacity-100"
          : "pointer-events-none translate-x-8 opacity-0",
      )}
      aria-hidden={!open}
    >
      <div
        className={cn(
          "hal-paper hal-sheet flex h-full min-h-0 flex-col rounded-[22px] border border-border shadow-popover transition-transform duration-normal ease-standard",
          open ? "translate-x-0" : "translate-x-6",
        )}
      >
        <div className="flex shrink-0 items-center border-b border-subtle px-5 py-4">
          <div>
            <p className="hal-rule-label">Brief</p>
            <p className="mt-2 text-meta text-hal-muted">
              Current thread synthesis, carried across sessions.
            </p>
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 md:px-6 md:py-6">
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

/** Build a short, more distinctive monogram for the working-mode thread rail. */
function threadMonogram(name: string, slug: string): string {
  const slugParts = slug
    .split("-")
    .map((part) => part.trim())
    .filter(Boolean);

  if (slugParts.length >= 2) {
    return `${slugParts[0]![0]}${slugParts[1]![0]}`.toUpperCase();
  }

  const compact = name.replace(/[^A-Za-z0-9\u4e00-\u9fff]/g, "").trim();
  if (compact.length >= 2) {
    return compact.slice(0, 2).toUpperCase();
  }

  return compact[0]?.toUpperCase() ?? "?";
}
