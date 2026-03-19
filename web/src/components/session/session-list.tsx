/**
 * SessionList -- Spacious thread-detail session list.
 */

import { useEffect, useState } from "react";
import { ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { halPaperObjectVariants } from "@/components/ui/hal-patterns";
import { StatusDot } from "@/components/ui/status-dot";
import type { SessionManifest, SessionStatus } from "@/lib/types";
import { formatTimestamp } from "@/lib/runtime";
import { cn } from "@/lib/utils";

interface SessionListProps {
  currentThreadSlug: string;
  sessions: SessionManifest[];
  selectedSessionId: string | null;
  onSelect: (sessionId: string) => void;
  onCreate: () => void;
  creating?: boolean;
}

type SessionGroupId = "active" | "briefed" | "dropped";

interface SessionGroupDefinition {
  id: SessionGroupId;
  label: string;
  statuses: SessionStatus[];
  dotState: "live" | "success" | "muted";
}

const SESSION_GROUPS: SessionGroupDefinition[] = [
  {
    id: "active",
    label: "ACTIVE",
    statuses: ["active", "briefing"],
    dotState: "live",
  },
  {
    id: "briefed",
    label: "BRIEFED",
    statuses: ["ended"],
    dotState: "success",
  },
  {
    id: "dropped",
    label: "DROPPED",
    statuses: ["dropped"],
    dotState: "muted",
  },
];

const DEFAULT_GROUP_OPEN_STATE: Record<SessionGroupId, boolean> = {
  active: true,
  briefed: true,
  dropped: false,
};

export function SessionList({
  currentThreadSlug,
  sessions,
  selectedSessionId,
  onSelect,
  onCreate,
  creating = false,
}: SessionListProps) {
  const [openGroups, setOpenGroups] = useState<Record<SessionGroupId, boolean>>(
    DEFAULT_GROUP_OPEN_STATE,
  );

  useEffect(() => {
    setOpenGroups(DEFAULT_GROUP_OPEN_STATE);
  }, [currentThreadSlug]);

  useEffect(() => {
    if (!selectedSessionId) return;
    const selectedGroup = findSessionGroup(selectedSessionId, sessions);
    if (!selectedGroup) return;
    setOpenGroups((current) =>
      current[selectedGroup] ? current : { ...current, [selectedGroup]: true },
    );
  }, [selectedSessionId, sessions]);

  return (
    <section className="flex min-h-0 flex-1 flex-col">
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="hal-rule-label">Sessions</p>
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
          <div
            className={cn(
              "hal-paper rounded-lg",
              halPaperObjectVariants({ density: "spacious" }),
            )}
          >
            <p className="text-subheading font-medium text-hal-primary">No sessions yet</p>
            <p className="mt-1 max-w-xl text-meta text-hal-muted">
              Start the first collaboration run for this thread when you are ready.
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {SESSION_GROUPS.map((group) => {
              const groupSessions = sessions.filter((session) =>
                group.statuses.includes(session.status),
              );
              if (groupSessions.length === 0) return null;

              const isOpen = openGroups[group.id];

              return (
                <section key={group.id} className="border-t border-subtle first:border-t-0">
                  <button
                    type="button"
                    onClick={() =>
                      setOpenGroups((current) => ({
                        ...current,
                        [group.id]: !current[group.id],
                      }))
                    }
                    className={cn(
                      "flex w-full items-center justify-between gap-3 py-1.5 text-left transition-colors duration-fast ease-standard",
                      isOpen ? "text-hal-primary" : "text-hal-muted hover:text-hal-primary",
                    )}
                    aria-expanded={isOpen}
                    aria-controls={`session-group-${group.id}`}
                  >
                    <div className="flex min-w-0 items-center gap-2.5">
                      <ChevronRight
                        className={cn(
                          "h-3.5 w-3.5 shrink-0 transition-transform duration-normal ease-standard motion-reduce:transition-none",
                          isOpen ? "rotate-90 text-hal-primary" : "text-hal-muted",
                        )}
                      />
                      <StatusDot state={group.dotState} className="h-1.5 w-1.5" />
                      <span className="font-mono text-meta font-medium tracking-[0.04em]">
                        {group.label}
                      </span>
                    </div>
                    <span className="shrink-0 font-mono text-caption text-hal-muted">
                      {groupSessions.length}
                    </span>
                  </button>

                  <div
                    id={`session-group-${group.id}`}
                    className={cn(
                      "grid overflow-hidden transition-[grid-template-rows,opacity] duration-normal ease-standard motion-reduce:transition-none",
                      isOpen ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-70",
                    )}
                  >
                    <div className="min-h-0 overflow-hidden">
                      <div className="space-y-0.5 pb-0.5">
                        {groupSessions.map((session) => {
                          const isSelected = session.session_id === selectedSessionId;
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
                                "w-full rounded-lg border px-3 py-2.5 text-left transition-colors duration-fast ease-standard",
                                isSelected
                                  ? "border-accent bg-hal-selection"
                                  : "border-transparent hover:bg-hal-hover",
                              )}
                            >
                              <div className="min-w-0">
                                <div className="font-mono text-body font-medium text-hal-primary">
                                  {formatTimestamp(session.created_at)}
                                </div>
                                <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-caption text-hal-muted">
                                  <span className="font-mono text-hal-muted">
                                    {session.turn_count} turn
                                    {session.turn_count === 1 ? "" : "s"}
                                  </span>
                                  {otherThreads.map((slug) => (
                                    <span
                                      key={slug}
                                      className="font-mono text-caption text-hal-muted"
                                    >
                                      +{slug}
                                    </span>
                                  ))}
                                </div>
                              </div>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                </section>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}

function findSessionGroup(
  sessionId: string,
  sessions: SessionManifest[],
): SessionGroupId | null {
  const session = sessions.find((item) => item.session_id === sessionId);
  if (!session) return null;
  return SESSION_GROUPS.find((group) => group.statuses.includes(session.status))?.id ?? null;
}
