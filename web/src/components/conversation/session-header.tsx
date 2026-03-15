/**
 * SessionHeader — compact action bar above the conversation.
 */

import { ArrowLeft } from "lucide-react";

import { Button } from "@/components/ui/button";
import { sessionDisplayState } from "@/lib/runtime";
import type { SessionManifest, SocketState } from "@/lib/types";
import { cn } from "@/lib/utils";

interface SessionHeaderProps {
  session: SessionManifest;
  threadName: string | null;
  socketState: SocketState;
  briefPanelOpen: boolean;
  onBack: () => void;
  onEditScope: () => void;
  onBrief: () => void;
  onDrop: () => void;
  onToggleBriefPanel: () => void;
}

export function SessionHeader({
  session,
  threadName,
  socketState,
  briefPanelOpen,
  onBack,
  onEditScope,
  onBrief,
  onDrop,
  onToggleBriefPanel,
}: SessionHeaderProps) {
  const canEndSession = session.status === "active";
  const canEditScope = session.status === "active";
  const showSocketState = session.status === "active" || session.status === "briefing";
  const status = sessionDisplayState(session.status);

  return (
    <header className="shrink-0 border-b border-subtle px-5 py-3 md:px-6">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <Button
            variant="ghost"
            size="icon"
            onClick={onBack}
            aria-label="Back to thread overview"
          >
            <ArrowLeft />
          </Button>
          <div className="flex min-w-0 items-center gap-2 text-meta">
            <span className="truncate font-medium text-hal-primary">
              {threadName ?? session.primary_thread ?? "Working log"}
            </span>
            <span className={cn("shrink-0 font-medium", status.textClass)}>
              {status.label}
            </span>
            {showSocketState ? (
              <span className="shrink-0 text-hal-muted">{socketLabel(socketState)}</span>
            ) : null}
          </div>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={onToggleBriefPanel}
            aria-pressed={briefPanelOpen}
            className={cn(briefPanelOpen && "bg-hal-panel text-hal-primary")}
          >
            {briefPanelOpen ? "Hide brief" : "Thread brief"}
          </Button>
          {canEditScope && (
            <Button variant="secondary" size="sm" onClick={onEditScope}>
              Scope
            </Button>
          )}
          {canEndSession && (
            <>
              <Button variant="primary" size="sm" onClick={onBrief}>
                Brief
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={onDrop}
                className="text-danger hover:border-danger hover:bg-hal-danger-subtle hover:text-danger"
              >
                Drop
              </Button>
            </>
          )}
        </div>
      </div>
    </header>
  );
}

function socketLabel(state: SocketState): string {
  switch (state) {
    case "live": return "stream live";
    case "connecting": return "connecting";
    case "disconnected": return "disconnected";
  }
}
