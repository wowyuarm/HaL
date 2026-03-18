/**
 * SessionHeader — compact action bar above the conversation.
 *
 * Back and overflow use contextual icon controls (muted, no fill).
 * Brief stays visible as primary action. Scope and Drop are in the
 * overflow menu to keep the header calm.
 */

import { ArrowLeft, MoreHorizontal } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
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
  const showOverflow = canEditScope || canEndSession;

  return (
    <header className="shrink-0 border-b border-subtle px-5 py-3 md:px-6">
      <div className="flex w-full items-center justify-between gap-3">
        {/* Left: navigation + context */}
        <div className="flex min-w-0 items-start gap-2">
          <Button
            variant="ghost"
            size="icon"
            onClick={onBack}
            aria-label="Back to thread overview"
          >
            <ArrowLeft />
          </Button>
          <div className="min-w-0 pt-0.5">
            <div className="truncate text-heading font-medium tracking-[-0.01em] text-hal-primary">
              {threadName ?? session.primary_thread ?? "Working log"}
            </div>
            <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-caption text-hal-muted">
              <span className={cn("font-mono font-medium", status.textClass)}>
                {status.label}
              </span>
              {showSocketState ? <span className="font-mono">{socketLabel(socketState)}</span> : null}
            </div>
          </div>
        </div>

        {/* Right: view toggle + primary action + overflow */}
        <div className="flex shrink-0 items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={onToggleBriefPanel}
            aria-pressed={briefPanelOpen}
            className={cn("h-7.5 w-[4.25rem]", briefPanelOpen && "border-accent")}
          >
            Thread
          </Button>
          {canEndSession && (
            <Button variant="primary" size="sm" onClick={onBrief} className="h-7.5 w-[4.25rem]">
              Brief
            </Button>
          )}
          {showOverflow && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label="Session actions"
                >
                  <MoreHorizontal />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {canEditScope && (
                  <DropdownMenuItem onSelect={onEditScope}>Edit scope</DropdownMenuItem>
                )}
                {canEndSession && (
                  <>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      onSelect={onDrop}
                      className="text-danger focus:text-danger"
                    >
                      Drop session
                    </DropdownMenuItem>
                  </>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
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
