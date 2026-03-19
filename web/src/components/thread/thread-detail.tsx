/**
 * ThreadDetailPanel -- Compact thread overview with sessions below.
 */

import { SessionList } from "@/components/session/session-list";
import { Button } from "@/components/ui/button";
import { HAL_READING_COLUMN_CLASS } from "@/components/ui/hal-patterns";
import type { ThreadDetail } from "@/lib/types";
import { cn } from "@/lib/utils";

interface ThreadDetailProps {
  thread: ThreadDetail | null;
  selectedSessionId: string | null;
  onSelectSession: (sessionId: string) => void;
  onCreateSession: () => void;
  onToggleBriefPanel: () => void;
  onUpdateSessionTitle: (
    sessionId: string,
    input: { title: string | null },
  ) => Promise<boolean> | boolean;
  onEndSession: (
    sessionId: string,
    reason: "brief" | "drop",
  ) => Promise<boolean> | boolean;
  onPreviewEpisode: (input: {
    threadSlug: string;
    episodeRelPath: string;
    episodeTitle: string;
  }) => void;
  creatingSession?: boolean;
}

export function ThreadDetailPanel({
  thread,
  selectedSessionId,
  onSelectSession,
  onCreateSession,
  onToggleBriefPanel,
  onUpdateSessionTitle,
  onEndSession,
  onPreviewEpisode,
  creatingSession = false,
}: ThreadDetailProps) {
  if (!thread) {
    return (
      <div className={cn(HAL_READING_COLUMN_CLASS, "flex h-full items-center justify-center")}>
        <section className="w-full rounded-md border border-dashed border-border p-6 text-body text-hal-muted">
          Select a thread to inspect its sessions.
        </section>
      </div>
    );
  }

  return (
    <section className="flex h-full min-h-0 flex-col">
      <header className="shrink-0 border-b border-subtle">
        <div className={cn(HAL_READING_COLUMN_CLASS, "flex items-start justify-between gap-4 px-5 py-5 md:px-6")}>
          <div className="min-w-0">
            <p className="hal-rule-label">Thread</p>
            <h2 className="mt-2.5 truncate text-title font-medium tracking-[-0.02em] text-hal-primary">
              {thread.name}
            </h2>
            <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-caption text-hal-muted">
              {thread.status ? (
                <span
                  className={
                    thread.status === "active"
                      ? "font-mono font-medium text-accent"
                      : "font-mono font-medium text-hal-muted"
                  }
                >
                  {thread.status}
                </span>
              ) : null}
              <span className="font-mono">
                {thread.sessions.length} session{thread.sessions.length === 1 ? "" : "s"}
              </span>
            </div>
            <p className="mt-3 max-w-2xl text-body text-hal-muted">
              {thread.description || "No description."}
            </p>
          </div>
          <Button
            variant="secondary"
            size="sm"
            onClick={onToggleBriefPanel}
            className="shrink-0 self-start whitespace-nowrap"
          >
            Thread brief
          </Button>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className={cn(HAL_READING_COLUMN_CLASS, "px-5 py-6 md:px-6")}>
          <SessionList
            currentThreadSlug={thread.slug}
            sessions={thread.sessions}
            episodeRefs={thread.episode_refs}
            selectedSessionId={selectedSessionId}
            onSelect={onSelectSession}
            onCreate={onCreateSession}
            onUpdateSessionTitle={onUpdateSessionTitle}
            onEndSession={onEndSession}
            onPreviewEpisode={onPreviewEpisode}
            creating={creatingSession}
          />
        </div>
      </div>
    </section>
  );
}
