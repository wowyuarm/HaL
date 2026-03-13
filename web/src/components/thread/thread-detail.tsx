import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { formatCount, formatTimestamp } from "@/lib/runtime";
import type { ThreadDetail } from "@/lib/types";
import { SessionList } from "@/components/session/session-list";

interface ThreadDetailProps {
  thread: ThreadDetail | null;
  selectedSessionId: string | null;
  onSelectSession: (sessionId: string) => void;
  onCreateSession: () => void;
  creatingSession?: boolean;
}

export function ThreadDetailPanel({
  thread,
  selectedSessionId,
  onSelectSession,
  onCreateSession,
  creatingSession = false,
}: ThreadDetailProps) {
  if (!thread) {
    return (
      <section className="flex h-full items-center justify-center rounded-lg border border-dashed border-border bg-elevated p-6 text-sm text-muted">
        Select a thread to inspect its brief and sessions.
      </section>
    );
  }

  return (
    <section className="flex h-full min-h-0 flex-col rounded-lg border border-border bg-elevated">
      <header className="border-b border-border px-5 py-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold text-foreground">{thread.name}</h2>
            <p className="mt-1 text-sm text-muted">{thread.description || "No description."}</p>
          </div>
          <span className="rounded-sm border border-border bg-panel px-2 py-1 font-mono text-[11px] uppercase tracking-wide text-muted">
            {thread.scope || "thread"}
          </span>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-3 text-xs text-muted">
          <div className="rounded-md border border-border bg-background px-3 py-2">
            <div className="font-medium uppercase tracking-wide text-muted">Updated</div>
            <div className="mt-1 text-foreground">
              {formatTimestamp(thread.updated_at)}
            </div>
          </div>
          <div className="rounded-md border border-border bg-background px-3 py-2">
            <div className="font-medium uppercase tracking-wide text-muted">Sessions</div>
            <div className="mt-1 text-foreground">
              {formatCount((thread.session_counts.active ?? 0) + (thread.session_counts.briefing ?? 0) + (thread.session_counts.ended ?? 0) + (thread.session_counts.dropped ?? 0))}
            </div>
          </div>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        <section className="mb-6">
          <p className="mb-3 text-xs font-medium uppercase tracking-widest text-muted">
            BRIEF.md
          </p>
          <div className="prose prose-mineral max-w-none rounded-md border border-border bg-background px-4 py-3 text-sm">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {thread.brief_markdown || "_This thread does not have a brief yet._"}
            </ReactMarkdown>
          </div>
        </section>

        <SessionList
          sessions={thread.sessions}
          selectedSessionId={selectedSessionId}
          onSelect={onSelectSession}
          onCreate={onCreateSession}
          creating={creatingSession}
        />
      </div>
    </section>
  );
}
