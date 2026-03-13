import { useEffect, useState } from "react";

import { WorkingLog } from "@/components/session/working-log";
import { SessionScopeDialog } from "@/components/session/session-scope-dialog";
import { SessionMountedThreadsDialog } from "@/components/session/session-mounted-threads-dialog";
import { ThreadDetailPanel } from "@/components/thread/thread-detail";
import { endSession, submitSessionTurn } from "@/lib/api";
import { ThreadList } from "@/components/thread/thread-list";
import { isInteractiveSession } from "@/lib/runtime";
import { useHalStore } from "@/lib/store";
import { useSessionSocket } from "@/lib/ws";

export default function App() {
  const [scopeDialogOpen, setScopeDialogOpen] = useState(false);
  const [scopeEditorOpen, setScopeEditorOpen] = useState(false);
  const [scopeEditorSessionId, setScopeEditorSessionId] = useState<string | null>(null);
  const threads = useHalStore((s) => s.threads);
  const threadDetails = useHalStore((s) => s.threadDetails);
  const sessionManifests = useHalStore((s) => s.sessionManifests);
  const sessionEvents = useHalStore((s) => s.sessionEvents);
  const activeThreadSlug = useHalStore((s) => s.activeThreadSlug);
  const selectedSessionId = useHalStore((s) => s.selectedSessionId);
  const socketState = useHalStore((s) => s.socketState);
  const loadingThreads = useHalStore((s) => s.loadingThreads);
  const loadingThreadSlug = useHalStore((s) => s.loadingThreadSlug);
  const loadingSessionId = useHalStore((s) => s.loadingSessionId);
  const creatingSession = useHalStore((s) => s.creatingSession);
  const updatingScopeSessionId = useHalStore((s) => s.updatingScopeSessionId);
  const lastError = useHalStore((s) => s.lastError);
  const loadThreads = useHalStore((s) => s.loadThreads);
  const loadThread = useHalStore((s) => s.loadThread);
  const loadSessionEvents = useHalStore((s) => s.loadSessionEvents);
  const applySessionManifest = useHalStore((s) => s.applySessionManifest);
  const selectThread = useHalStore((s) => s.selectThread);
  const selectSession = useHalStore((s) => s.selectSession);
  const createSessionForThread = useHalStore((s) => s.createSessionForThread);
  const createScopedSession = useHalStore((s) => s.createScopedSession);
  const updateSessionScope = useHalStore((s) => s.updateSessionScope);
  const setError = useHalStore((s) => s.setError);

  const activeThread = activeThreadSlug ? threadDetails[activeThreadSlug] ?? null : null;
  const selectedSession = selectedSessionId ? sessionManifests[selectedSessionId] ?? null : null;
  const scopeEditorSession = scopeEditorSessionId
    ? sessionManifests[scopeEditorSessionId] ?? null
    : null;
  const loadingThread = Boolean(activeThreadSlug && loadingThreadSlug === activeThreadSlug);
  const loadingSession = Boolean(selectedSessionId && loadingSessionId === selectedSessionId);
  const events = selectedSessionId ? sessionEvents[selectedSessionId] ?? [] : [];
  const latestEventSeq = events.at(-1)?.seq ?? 0;
  useSessionSocket(
    selectedSession?.session_id ?? null,
    selectedSession?.status ?? null,
  );

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
      const manifest = await submitSessionTurn(selectedSession.session_id, { content });
      if (socketState !== "live") {
        applySessionManifest(manifest);
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

  return (
    <div className="flex h-screen bg-background text-foreground">
      <aside className="flex h-screen w-[240px] shrink-0 flex-col border-r border-border bg-panel">
        <div className="flex-1 overflow-y-auto px-3 py-4">
          <div className="flex items-center justify-between gap-2 px-2">
            <p className="text-xs font-medium uppercase tracking-widest text-muted">Threads</p>
            <button
              type="button"
              onClick={() => setScopeDialogOpen(true)}
              disabled={threads.length === 0 || creatingSession}
              className="rounded-md border border-border bg-elevated px-2.5 py-1 text-[11px] font-medium uppercase tracking-wide text-foreground transition-colors duration-fast ease-standard hover:bg-background disabled:cursor-not-allowed disabled:opacity-50"
            >
              Scope
            </button>
          </div>
          <div className="mt-3">
            <ThreadList
              threads={threads}
              activeThread={activeThreadSlug}
              onSelect={handleSelectThread}
            />
          </div>
        </div>
        <div className="border-t border-border px-3 py-4">
          <div className="rounded-md border border-border bg-elevated px-3 py-3 text-xs text-muted">
            <p className="font-medium uppercase tracking-widest text-foreground">
              Working Log
            </p>
            <p className="mt-2 leading-relaxed">
              Threads hold durable memory. Sessions are the observable work runs beneath them.
            </p>
          </div>
        </div>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col bg-background">
        <header className="flex h-12 shrink-0 items-center gap-3 border-b border-border px-5">
          <h1 className="text-sm font-semibold text-foreground">
            {activeThread?.name ?? "HaL"}
          </h1>
          {activeThread?.scope && (
            <span className="rounded-sm border border-border bg-elevated px-1.5 py-0.5 font-mono text-[11px] text-muted">
              {activeThread.scope}
            </span>
          )}
          <span className="rounded-sm border border-border bg-elevated px-1.5 py-0.5 text-[11px] font-medium text-muted">
            {selectedSession ? `socket ${socketState}` : "select a session"}
          </span>
          {(loadingThreads || loadingThread || loadingSession) && (
            <span className="rounded-sm bg-panel px-1.5 py-0.5 text-[11px] font-medium text-muted">
              loading
            </span>
          )}
        </header>

        <div className="grid min-h-0 flex-1 gap-4 p-4 xl:grid-cols-[minmax(360px,420px)_minmax(0,1fr)]">
          <ThreadDetailPanel
            thread={activeThread}
            selectedSessionId={selectedSessionId}
            onSelectSession={handleSelectSession}
            onCreateSession={handleCreateSession}
            creatingSession={creatingSession}
          />
          <WorkingLog
            session={selectedSession}
            events={events}
            socketState={socketState}
            scopeEditable={threads.length > 0}
            loading={loadingThread || loadingSession}
            error={lastError}
            onSend={handleSend}
            onEditScope={handleOpenScopeEditor}
            onBrief={handleBrief}
            onDrop={handleDrop}
          />
        </div>
      </main>

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
