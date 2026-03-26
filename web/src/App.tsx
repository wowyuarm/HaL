/**
 * App — root composition shell.
 *
 * Two-column layout: persistent Sidebar (thread→session tree) + Main area
 * showing either ThreadDetailPanel (when browsing threads) or HalThread
 * (when a session is selected). Replaces the previous three-mode
 * (navigation/working/review) grid layout.
 */

import { useEffect, useState } from 'react'
import { AssistantRuntimeProvider } from '@assistant-ui/react'

import { HalThread } from '@/components/conversation/hal-thread'
import { Sidebar } from '@/components/layout/sidebar'
import { ProcessRail } from '@/components/session/process-rail'
import { ReviewPanel } from '@/components/session/review-panel'
import { SessionMountedThreadsDialog } from '@/components/session/session-mounted-threads-dialog'
import { ThreadDetailPanel } from '@/components/thread/thread-detail'
import { endSession } from '@/lib/api'
import { isInteractiveSession } from '@/lib/runtime'
import { useHalStore } from '@/lib/store'
import { useHalRuntime } from '@/lib/use-hal-runtime'
import { useSessionSocket } from '@/lib/ws'

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

export default function App() {
  const [scopeEditorOpen, setScopeEditorOpen] = useState(false)
  const [scopeEditorSessionId, setScopeEditorSessionId] = useState<string | null>(null)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

  // Store selectors
  const threads = useHalStore((s) => s.threads)
  const threadDetails = useHalStore((s) => s.threadDetails)
  const sessionManifests = useHalStore((s) => s.sessionManifests)
  const sessionEvents = useHalStore((s) => s.sessionEvents)
  const activeThreadSlug = useHalStore((s) => s.activeThreadSlug)
  const selectedSessionId = useHalStore((s) => s.selectedSessionId)
  const socketState = useHalStore((s) => s.socketState)
  const creatingSession = useHalStore((s) => s.creatingSession)
  const updatingScopeSessionId = useHalStore((s) => s.updatingScopeSessionId)
  const lastError = useHalStore((s) => s.lastError)
  const reviewPanel = useHalStore((s) => s.reviewPanel)

  // Store actions
  const loadThreads = useHalStore((s) => s.loadThreads)
  const loadThread = useHalStore((s) => s.loadThread)
  const loadSessionEvents = useHalStore((s) => s.loadSessionEvents)
  const applySessionManifest = useHalStore((s) => s.applySessionManifest)
  const selectThread = useHalStore((s) => s.selectThread)
  const selectSession = useHalStore((s) => s.selectSession)
  const createSessionForThread = useHalStore((s) => s.createSessionForThread)
  const updateSessionScope = useHalStore((s) => s.updateSessionScope)
  const updateSessionTitle = useHalStore((s) => s.updateSessionTitle)
  const openEpisode = useHalStore((s) => s.openEpisode)
  const toggleBriefPanel = useHalStore((s) => s.toggleBriefPanel)
  const setError = useHalStore((s) => s.setError)

  // Derived values
  const activeThread = activeThreadSlug ? (threadDetails[activeThreadSlug] ?? null) : null
  const selectedSession = selectedSessionId ? (sessionManifests[selectedSessionId] ?? null) : null
  const scopeEditorSession = scopeEditorSessionId
    ? (sessionManifests[scopeEditorSessionId] ?? null)
    : null
  const events = selectedSessionId ? (sessionEvents[selectedSessionId] ?? []) : []
  const latestEventSeq = events.at(-1)?.seq ?? 0
  const hasSession = Boolean(selectedSession)
  const briefPanelOpen = reviewPanel?.kind === 'brief'

  // WebSocket lifecycle
  useSessionSocket(selectedSession?.session_id ?? null, selectedSession?.status ?? null)

  // assistant-ui runtime bridge
  const halRuntime = useHalRuntime(selectedSessionId)

  // --- Data loading effects ---

  useEffect(() => {
    void loadThreads()
  }, [loadThreads])

  useEffect(() => {
    if (!activeThreadSlug) return
    void loadThread(activeThreadSlug)
  }, [activeThreadSlug, loadThread])

  useEffect(() => {
    if (!selectedSession) return
    if (latestEventSeq >= selectedSession.last_event_seq) return
    if (isInteractiveSession(selectedSession.status) && socketState === 'live') return
    void loadSessionEvents(selectedSession.session_id)
  }, [
    latestEventSeq,
    loadSessionEvents,
    selectedSession?.last_event_seq,
    selectedSession?.session_id,
    selectedSession?.status,
    socketState,
  ])

  // --- Event handlers ---

  const handleSelectThread = (slug: string) => {
    setError(null)
    selectThread(slug)
  }

  const handleSelectSession = (sessionId: string) => {
    setError(null)
    selectSession(sessionId)
  }

  const handleBack = () => selectSession(null)

  const handleCreateSession = async () => {
    if (!activeThreadSlug) return
    setError(null)
    await createSessionForThread(activeThreadSlug)
  }

  const closeScopeEditor = () => {
    if (updatingScopeSessionId) return
    setScopeEditorOpen(false)
    setScopeEditorSessionId(null)
  }

  const handleOpenScopeEditor = () => {
    if (!selectedSession) return
    setError(null)
    setScopeEditorSessionId(selectedSession.session_id)
    setScopeEditorOpen(true)
  }

  const handlePreviewEpisode = (episodeRef: {
    threadSlug: string
    episodeRelPath: string
    episodeTitle: string
  }) => {
    setError(null)
    openEpisode({
      threadSlug: episodeRef.threadSlug,
      episodePath: episodeRef.episodeRelPath,
      episodeTitle: episodeRef.episodeTitle,
    })
  }

  const handleUpdateScope = async (input: { addThreads: string[]; removeThreads: string[] }) => {
    if (!scopeEditorSession) return
    const hasChanges = input.addThreads.length > 0 || input.removeThreads.length > 0
    if (!hasChanges) {
      closeScopeEditor()
      return
    }
    setError(null)
    const manifest = await updateSessionScope(scopeEditorSession.session_id, input)
    if (manifest) closeScopeEditor()
  }

  const handleBrief = async () => {
    if (!selectedSession) return
    setError(null)
    try {
      const manifest = await endSession(selectedSession.session_id, { reason: 'brief' })
      applySessionManifest(manifest)
      if (socketState !== 'live') {
        await loadSessionEvents(selectedSession.session_id)
        if (activeThreadSlug) {
          await loadThread(activeThreadSlug, { adoptSelection: false })
        }
      }
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Failed to start briefing.')
    }
  }

  const handleDrop = async () => {
    if (!selectedSession) return
    setError(null)
    try {
      const manifest = await endSession(selectedSession.session_id, { reason: 'drop' })
      applySessionManifest(manifest)
      if (socketState !== 'live') {
        await loadSessionEvents(selectedSession.session_id)
        if (activeThreadSlug) {
          await loadThread(activeThreadSlug, { adoptSelection: false })
        }
      }
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Failed to drop session.')
    }
  }

  const handleUpdateSessionTitle = async (
    sessionId: string,
    input: { title: string | null },
  ): Promise<boolean> => {
    setError(null)
    const manifest = await updateSessionTitle(sessionId, input)
    return Boolean(manifest)
  }

  const handleEndSessionFromThreadDetail = async (
    sessionId: string,
    reason: 'brief' | 'drop',
  ): Promise<boolean> => {
    setError(null)
    try {
      const manifest = await endSession(sessionId, { reason })
      applySessionManifest(manifest)
      await loadSessionEvents(sessionId)
      if (activeThreadSlug) {
        await loadThread(activeThreadSlug, { adoptSelection: false })
      }
      return true
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : reason === 'brief'
            ? 'Failed to start briefing.'
            : 'Failed to drop session.',
      )
      return false
    }
  }

  // --- Render ---

  return (
    <AssistantRuntimeProvider runtime={halRuntime}>
      <div className="relative flex h-screen min-h-screen overflow-hidden bg-hal-canvas text-hal-primary">
        {/* Background texture */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 opacity-60 [background-image:repeating-linear-gradient(180deg,transparent_0,transparent_31px,rgba(36,33,29,0.03)_32px)]"
        />

        {/* Sidebar */}
        <Sidebar
          threads={threads}
          activeThreadSlug={activeThreadSlug}
          collapsed={sidebarCollapsed}
          onSelectThread={handleSelectThread}
          onToggleCollapse={() => setSidebarCollapsed((v) => !v)}
        />

        <div className="relative z-10 flex min-h-0 min-w-0 flex-1 overflow-hidden">
          {/* Main area */}
          <main className="min-h-0 min-w-0 flex-1 overflow-hidden">
            {lastError && (
              <div className="mx-3 mt-3 rounded-xl border border-danger bg-hal-danger-subtle px-4 py-3 text-body text-danger md:mx-5 lg:mx-7">
                {lastError}
              </div>
            )}
            {hasSession && selectedSession ? (
              <HalThread
                key={selectedSession.session_id}
                session={selectedSession}
                threadName={activeThread?.name ?? null}
                socketState={socketState}
                briefPanelOpen={briefPanelOpen}
                onBack={handleBack}
                onEditScope={handleOpenScopeEditor}
                onBrief={handleBrief}
                onDrop={handleDrop}
                onToggleBriefPanel={toggleBriefPanel}
              />
            ) : (
              <div className="h-full px-3 py-4 md:px-5 md:py-5 lg:px-7 lg:py-7">
                <ThreadDetailPanel
                  thread={activeThread}
                  selectedSessionId={selectedSessionId}
                  onSelectSession={handleSelectSession}
                  onCreateSession={handleCreateSession}
                  onUpdateSessionTitle={handleUpdateSessionTitle}
                  onEndSession={handleEndSessionFromThreadDetail}
                  onPreviewEpisode={handlePreviewEpisode}
                  creatingSession={creatingSession}
                  onToggleBriefPanel={toggleBriefPanel}
                />
              </div>
            )}
          </main>

          <ProcessRail />
        </div>

        {/* External review panel */}
        <ReviewPanel
          briefMarkdown={activeThread?.brief_markdown ?? null}
          threadSlug={activeThread?.slug ?? null}
        />

        {/* Dialogs */}
        <SessionMountedThreadsDialog
          open={scopeEditorOpen}
          session={scopeEditorSession}
          threads={threads}
          submitting={updatingScopeSessionId === scopeEditorSessionId}
          onClose={closeScopeEditor}
          onSubmit={handleUpdateScope}
        />
      </div>
    </AssistantRuntimeProvider>
  )
}
