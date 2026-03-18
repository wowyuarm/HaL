/**
 * SessionList -- Spacious thread-detail session list.
 */

import { Button } from "@/components/ui/button";
import { halPaperObjectVariants } from "@/components/ui/hal-patterns";
import type { SessionManifest } from "@/lib/types";
import { formatTimestamp, sessionDisplayState } from "@/lib/runtime";
import { cn } from "@/lib/utils";

interface SessionListProps {
  currentThreadSlug: string;
  sessions: SessionManifest[];
  selectedSessionId: string | null;
  onSelect: (sessionId: string) => void;
  onCreate: () => void;
  creating?: boolean;
}

export function SessionList({
  currentThreadSlug,
  sessions,
  selectedSessionId,
  onSelect,
  onCreate,
  creating = false,
}: SessionListProps) {
  return (
    <section className="flex min-h-0 flex-1 flex-col">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="hal-rule-label">Sessions</p>
          <h3 className="mt-2.5 text-heading font-medium tracking-[-0.01em] text-hal-primary">
            Collaboration runs
          </h3>
        </div>
        <Button
          variant="primary"
          size="sm"
          onClick={onCreate}
          disabled={creating}
        >
          {creating ? "Creating..." : "New Session"}
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {sessions.length === 0 ? (
          <div className={cn("hal-paper rounded-lg", halPaperObjectVariants({ density: "spacious" }))}>
            <p className="text-subheading font-medium text-hal-primary">No sessions yet</p>
            <p className="mt-1.5 max-w-xl text-meta text-hal-muted">
              Start the first collaboration run for this thread when you are ready.
            </p>
          </div>
        ) : (
          <div className="space-y-1">
            {sessions.map((session) => {
              const isSelected = session.session_id === selectedSessionId;
              const status = sessionDisplayState(session.status);
              const scopeThreads = new Set(session.mounted_threads);
              if (session.primary_thread) {
                scopeThreads.add(session.primary_thread);
              }
              const otherThreads = [...scopeThreads]
                .filter((slug) => slug !== currentThreadSlug)
                .sort();

              return (
                <button
                  key={session.session_id}
                  type="button"
                  onClick={() => onSelect(session.session_id)}
                  className={cn(
                    "w-full rounded-lg border px-4 py-3.5 text-left transition-colors duration-fast ease-standard",
                    isSelected
                      ? "border-accent bg-hal-selection"
                      : "border-transparent hover:bg-hal-hover",
                  )}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="font-mono text-body font-medium text-hal-primary">
                        {formatTimestamp(session.created_at)}
                      </div>
                      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-caption text-hal-muted">
                        <span className="font-mono text-hal-muted">
                          {session.turn_count} turn{session.turn_count === 1 ? "" : "s"}
                        </span>
                        {otherThreads.map((slug) => (
                          <span key={slug} className="font-mono text-caption text-hal-muted">
                            +{slug}
                          </span>
                        ))}
                      </div>
                    </div>
                    <span
                      className={cn(
                        "shrink-0 pt-0.5 font-mono text-caption font-medium uppercase tracking-[0.08em]",
                        status.textClass,
                      )}
                    >
                      {status.label}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}
