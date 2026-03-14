/**
 * ThreadDetailPanel -- Navigation-mode thread detail view.
 *
 * Shows thread name, description, scope tag, BRIEF.md prose rendering,
 * metadata (updated timestamp, session count), and session list below.
 * Navigation mode stays on the shared canvas with the BRIEF centered for
 * reading comfort instead of wrapping the whole detail view in a card.
 */

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { SessionList } from "@/components/session/session-list";
import { Tag } from "@/components/ui/tag";
import { formatCount, formatTimestamp } from "@/lib/runtime";
import type { ThreadDetail } from "@/lib/types";

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
      <section className="flex h-full items-center justify-center rounded-md border border-dashed border-border p-6 text-body text-hal-muted">
        Select a thread to inspect its brief and sessions.
      </section>
    );
  }

  const totalSessions =
    (thread.session_counts.active ?? 0) +
    (thread.session_counts.briefing ?? 0) +
    (thread.session_counts.ended ?? 0) +
    (thread.session_counts.dropped ?? 0);

  return (
    <section className="flex h-full min-h-0 flex-col">
      <header className="mx-auto w-full max-w-5xl border-b border-subtle px-2 pb-5 pt-1">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h2 className="truncate text-heading text-hal-primary">
              {thread.name}
            </h2>
            <p className="mt-2 max-w-3xl text-body text-hal-muted">
              {thread.description || "No description."}
            </p>
          </div>
          <Tag>{thread.scope || "thread"}</Tag>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-meta text-hal-muted">
          <span>Updated {formatTimestamp(thread.updated_at)}</span>
          <span>{formatCount(totalSessions)} sessions</span>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-8 px-2 py-6">
          <section className="mx-auto w-full max-w-3xl">
            <p className="mb-4 text-caption uppercase tracking-widest text-hal-muted">
            BRIEF.md
            </p>
            <div className="prose prose-mineral max-w-none text-[15px] leading-7 text-hal-primary">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {thread.brief_markdown || "_This thread does not have a brief yet._"}
              </ReactMarkdown>
            </div>
          </section>

          <section className="border-t border-subtle pt-5">
            <SessionList
              sessions={thread.sessions}
              selectedSessionId={selectedSessionId}
              onSelect={onSelectSession}
              onCreate={onCreateSession}
              creating={creatingSession}
            />
          </section>
        </div>
      </div>
    </section>
  );
}
