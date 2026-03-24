/**
 * HalThread — root conversation component using assistant-ui primitives.
 *
 * Assembles the session header, message list (with auto-scroll),
 * and composer into a full conversation view. This replaces
 * the 807-line WorkingLog component.
 */

import { ThreadPrimitive } from '@assistant-ui/react'

import { HalAssistantMessage } from '@/components/conversation/hal-assistant-message'
import { HalComposer } from '@/components/conversation/hal-composer'
import { SessionHeader } from '@/components/conversation/session-header'
import { HalSystemMessage } from '@/components/conversation/hal-system-message'
import { HalUserMessage } from '@/components/conversation/hal-user-message'
import { HAL_READING_COLUMN_CLASS } from '@/components/ui/hal-patterns'
import { Panel } from '@/components/ui/panel'
import { cn } from '@/lib/utils'
import { isInteractiveSession } from '@/lib/runtime'
import { useHalStore } from '@/lib/store'
import type { SessionManifest, SocketState } from '@/lib/types'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface HalThreadProps {
  session: SessionManifest
  threadName: string | null
  socketState: SocketState
  briefPanelOpen: boolean
  onBack: () => void
  onEditScope: () => void
  onBrief: () => void
  onDrop: () => void
  onToggleBriefPanel: () => void
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function HalThread({
  session,
  threadName,
  socketState,
  briefPanelOpen,
  onBack,
  onEditScope,
  onBrief,
  onDrop,
  onToggleBriefPanel,
}: HalThreadProps) {
  const interactive = isInteractiveSession(session.status)

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden">
      <SessionHeader
        session={session}
        threadName={threadName}
        socketState={socketState}
        briefPanelOpen={briefPanelOpen}
        onBack={onBack}
        onEditScope={onEditScope}
        onBrief={onBrief}
        onDrop={onDrop}
        onToggleBriefPanel={onToggleBriefPanel}
      />

      <ThreadPrimitive.Root className="relative flex min-h-0 flex-1 flex-col">
        <ThreadPrimitive.Viewport className="min-h-0 flex-1 overflow-y-auto px-3 py-6 md:px-5 md:py-7">
          <ThreadPrimitive.Empty>
            <EmptyState />
          </ThreadPrimitive.Empty>

          <div className={cn(HAL_READING_COLUMN_CLASS, 'space-y-5')}>
            <ThreadPrimitive.Messages
              components={{
                UserMessage: HalUserMessage,
                AssistantMessage: HalAssistantMessage,
                SystemMessage: HalSystemMessage,
              }}
            />
          </div>

          <ThreadPrimitive.ViewportFooter className="h-36 md:h-40" />
        </ThreadPrimitive.Viewport>

        {interactive && (
          <div className="pointer-events-none absolute inset-x-0 bottom-0 z-20 px-3 pb-4 pt-8 md:px-5 md:pb-5">
            <div className="pointer-events-none mx-auto w-full max-w-[56rem] bg-gradient-to-t from-hal-canvas via-hal-canvas/92 to-transparent pt-8">
              <div className="pointer-events-auto">
                <HalComposer />
              </div>
            </div>
          </div>
        )}
      </ThreadPrimitive.Root>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

function EmptyState() {
  return (
    <div className={HAL_READING_COLUMN_CLASS}>
      <Panel
        surface="base"
        border
        className="hal-paper hal-sheet rounded-md border-dashed px-5 py-6 text-body text-hal-muted"
      >
        <p className="hal-rule-label">Working Log</p>
        <p className="mt-4 max-w-xl text-reading text-hal-muted">
          No observable events have been recorded for this session yet. If this is an active run,
          the log will fill in as the event stream reconnects or new turns begin.
        </p>
      </Panel>
    </div>
  )
}
