/**
 * SessionList -- Spacious thread-detail session list.
 */

import { useEffect, useState } from "react";
import { Check, ChevronRight, MoreHorizontal, ScrollText, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { halPaperObjectVariants } from "@/components/ui/hal-patterns";
import { StatusDot } from "@/components/ui/status-dot";
import type { SessionManifest, SessionStatus, ThreadEpisodeRef } from "@/lib/types";
import { formatTimestamp } from "@/lib/runtime";
import { normalizeMixedScriptSpacing } from "@/lib/text";
import { cn } from "@/lib/utils";

interface SessionListProps {
  currentThreadSlug: string;
  sessions: SessionManifest[];
  episodeRefs?: Record<string, ThreadEpisodeRef>;
  selectedSessionId: string | null;
  onSelect: (sessionId: string) => void;
  onCreate: () => void;
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
  episodeRefs = {},
  selectedSessionId,
  onSelect,
  onCreate,
  onUpdateSessionTitle,
  onEndSession,
  onPreviewEpisode,
  creating = false,
}: SessionListProps) {
  const [openGroups, setOpenGroups] = useState<Record<SessionGroupId, boolean>>(
    DEFAULT_GROUP_OPEN_STATE,
  );
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const [savingTitle, setSavingTitle] = useState(false);
  const [endingSessionId, setEndingSessionId] = useState<string | null>(null);

  useEffect(() => {
    setOpenGroups(DEFAULT_GROUP_OPEN_STATE);
  }, [currentThreadSlug]);

  useEffect(() => {
    setEditingSessionId(null);
    setDraftTitle("");
    setSavingTitle(false);
    setEndingSessionId(null);
  }, [currentThreadSlug]);

  useEffect(() => {
    if (!selectedSessionId) return;
    const selectedGroup = findSessionGroup(selectedSessionId, sessions);
    if (!selectedGroup) return;
    setOpenGroups((current) =>
      current[selectedGroup] ? current : { ...current, [selectedGroup]: true },
    );
  }, [selectedSessionId, sessions]);

  useEffect(() => {
    if (!editingSessionId) return;
    const session = sessions.find((item) => item.session_id === editingSessionId);
    if (!session) {
      setEditingSessionId(null);
      setDraftTitle("");
      setSavingTitle(false);
      return;
    }
    setDraftTitle(session.title ?? "");
  }, [editingSessionId, sessions]);

  const beginEditing = (session: SessionManifest) => {
    setEditingSessionId(session.session_id);
    setDraftTitle(session.title ?? "");
    setSavingTitle(false);
  };

  const cancelEditing = () => {
    if (savingTitle) return;
    setEditingSessionId(null);
    setDraftTitle("");
  };

  const submitTitle = async (sessionId: string) => {
    setSavingTitle(true);
    const success = await onUpdateSessionTitle(sessionId, {
      title: normalizeDraftTitle(draftTitle),
    });
    setSavingTitle(false);
    if (!success) return;
    setEditingSessionId(null);
    setDraftTitle("");
  };

  const endSessionFromList = async (sessionId: string, reason: "brief" | "drop") => {
    setEndingSessionId(sessionId);
    const success = await onEndSession(sessionId, reason);
    setEndingSessionId((current) => (current === sessionId ? null : current));
    return success;
  };

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
                          const isEditing = session.session_id === editingSessionId;
                          const hasTitle = Boolean(session.title?.trim());
                          const title = displaySessionTitle(session);
                          const episodeRef = episodeRefs[session.session_id] ?? null;
                          const canEndSession = session.status === "active";
                          const sessionEnding = endingSessionId === session.session_id;
                          const scopeThreads = new Set(session.mounted_threads);
                          if (session.primary_thread) {
                            scopeThreads.add(session.primary_thread);
                          }
                          const otherThreads = [...scopeThreads]
                            .filter((slug) => slug !== currentThreadSlug)
                            .sort();

                          return (
                            <div key={session.session_id} className="group/session relative">
                              <div
                                role={isEditing ? undefined : "button"}
                                tabIndex={isEditing ? undefined : 0}
                                onClick={
                                  isEditing
                                    ? undefined
                                    : () => {
                                        onSelect(session.session_id);
                                      }
                                }
                                onKeyDown={
                                  isEditing
                                    ? undefined
                                    : (event) => {
                                        if (event.key === "Enter" || event.key === " ") {
                                          event.preventDefault();
                                          onSelect(session.session_id);
                                        }
                                      }
                                }
                                className={cn(
                                  "w-full rounded-lg border px-3 py-2.5 pr-16 text-left transition-colors duration-fast ease-standard",
                                  !isEditing && "cursor-pointer",
                                  isEditing || isSelected
                                    ? "border-accent bg-hal-selection"
                                    : "border-transparent hover:bg-hal-hover",
                                )}
                              >
                                <div className="min-w-0">
                                  {isEditing ? (
                                    <input
                                      autoFocus
                                      value={draftTitle}
                                      onChange={(event) => setDraftTitle(event.target.value)}
                                      onKeyDown={(event) => {
                                        if (event.key === "Enter") {
                                          event.preventDefault();
                                          void submitTitle(session.session_id);
                                        }
                                        if (event.key === "Escape") {
                                          event.preventDefault();
                                          cancelEditing();
                                        }
                                      }}
                                      placeholder="Untitled session"
                                      className={cn(
                                        "w-full border-0 border-b border-border bg-transparent px-0 py-0 text-body font-medium text-hal-primary placeholder:text-hal-muted",
                                        "focus:border-accent focus:outline-none",
                                      )}
                                    />
                                  ) : (
                                    <span
                                      className={cn(
                                        "block truncate text-body font-medium text-hal-primary",
                                        hasTitle ? "font-sans tracking-[-0.01em]" : "font-mono",
                                      )}
                                    >
                                      {title}
                                    </span>
                                  )}
                                  <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-caption text-hal-muted">
                                    {hasTitle ? (
                                      <span className="font-mono text-hal-muted">
                                        {formatTimestamp(session.created_at)}
                                      </span>
                                    ) : null}
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
                              </div>

                              <div
                                className={cn(
                                  "absolute inset-y-0 right-2 flex items-center gap-1 transition-opacity duration-fast ease-standard",
                                  isEditing
                                    ? "opacity-100 pointer-events-auto"
                                    : "opacity-0 pointer-events-none group-hover/session:opacity-100 group-focus-within/session:opacity-100 group-hover/session:pointer-events-auto group-focus-within/session:pointer-events-auto",
                                )}
                              >
                                {isEditing ? (
                                  <>
                                    <Button
                                      variant="ghost"
                                      size="icon"
                                      className="h-7 w-7 rounded-md pointer-events-auto"
                                      onClick={() => void submitTitle(session.session_id)}
                                      disabled={savingTitle}
                                      aria-label="Save session name"
                                    >
                                      <Check className="h-4 w-4" />
                                    </Button>
                                    <Button
                                      variant="ghost"
                                      size="icon"
                                      className="h-7 w-7 rounded-md pointer-events-auto"
                                      onClick={cancelEditing}
                                      disabled={savingTitle}
                                      aria-label="Cancel editing session name"
                                    >
                                      <X className="h-4 w-4" />
                                    </Button>
                                  </>
                                ) : (
                                  <>
                                    {episodeRef && session.status === "ended" ? (
                                      <Button
                                        variant="ghost"
                                        size="icon"
                                        className="h-7 w-7 rounded-md pointer-events-auto"
                                        onClick={() =>
                                          onPreviewEpisode({
                                            threadSlug: episodeRef.thread_slug,
                                            episodeRelPath: episodeRef.episode_rel_path,
                                            episodeTitle: episodeRef.episode_title,
                                          })
                                        }
                                        aria-label="Open episode"
                                        title="Open episode"
                                      >
                                        <ScrollText className="h-4 w-4" />
                                      </Button>
                                    ) : null}

                                    <DropdownMenu>
                                      <DropdownMenuTrigger asChild>
                                        <Button
                                          variant="ghost"
                                          size="icon"
                                          className="h-7 w-7 rounded-md pointer-events-auto"
                                          aria-label="Session actions"
                                          disabled={sessionEnding}
                                        >
                                          <MoreHorizontal className="h-4 w-4" />
                                        </Button>
                                      </DropdownMenuTrigger>
                                      <DropdownMenuContent align="end">
                                        <DropdownMenuItem onSelect={() => beginEditing(session)}>
                                          Edit name
                                        </DropdownMenuItem>
                                        {canEndSession ? (
                                          <>
                                            <DropdownMenuSeparator />
                                            <DropdownMenuItem
                                              onSelect={() => {
                                                void endSessionFromList(session.session_id, "brief");
                                              }}
                                              disabled={sessionEnding}
                                              className="text-accent focus:text-accent"
                                            >
                                              Brief
                                            </DropdownMenuItem>
                                            <DropdownMenuItem
                                              onSelect={() => {
                                                void endSessionFromList(session.session_id, "drop");
                                              }}
                                              disabled={sessionEnding}
                                              className="text-danger focus:text-danger"
                                            >
                                              Drop session
                                            </DropdownMenuItem>
                                          </>
                                        ) : null}
                                      </DropdownMenuContent>
                                    </DropdownMenu>
                                  </>
                                )}
                              </div>
                            </div>
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

function displaySessionTitle(session: SessionManifest): string {
  const title = session.title?.trim();
  if (title) return normalizeMixedScriptSpacing(title);
  return formatTimestamp(session.created_at);
}

function normalizeDraftTitle(value: string): string | null {
  const normalized = normalizeMixedScriptSpacing(value.trim());
  return normalized.length > 0 ? normalized : null;
}
