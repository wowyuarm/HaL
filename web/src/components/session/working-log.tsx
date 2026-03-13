import { useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { Composer } from "@/components/chat/composer";
import {
  buildWorkingLogItems,
  eventSummary,
  extractTextBlock,
  formatTimestamp,
  isInteractiveSession,
  sessionDisplayState,
} from "@/lib/runtime";
import type {
  SessionEvent,
  SessionManifest,
  SocketState,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const AUTO_SCROLL_THRESHOLD = 120;

interface WorkingLogProps {
  session: SessionManifest | null;
  events: SessionEvent[];
  socketState: SocketState;
  scopeEditable?: boolean;
  loading?: boolean;
  error?: string | null;
  onSend: (content: string) => void;
  onEditScope: () => void;
  onBrief: () => void;
  onDrop: () => void;
}

export function WorkingLog({
  session,
  events,
  socketState,
  scopeEditable = false,
  loading = false,
  error = null,
  onSend,
  onEditScope,
  onBrief,
  onDrop,
}: WorkingLogProps) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const wasNearBottomRef = useRef(true);
  const items = buildWorkingLogItems(events);
  const display = session ? sessionDisplayState(session.status) : null;
  const canSend = Boolean(session && session.status === "active");
  const canEndSession = Boolean(session && session.status === "active");
  const canEditScope = Boolean(scopeEditable && session?.status === "active");
  const interactive = Boolean(session && isInteractiveSession(session.status));

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;

    const handleScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = viewport;
      wasNearBottomRef.current = scrollHeight - scrollTop - clientHeight < AUTO_SCROLL_THRESHOLD;
    };

    viewport.addEventListener("scroll", handleScroll, { passive: true });
    return () => viewport.removeEventListener("scroll", handleScroll);
  }, []);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport || !wasNearBottomRef.current) return;
    viewport.scrollTop = viewport.scrollHeight;
  }, [events]);

  if (!session) {
    return (
      <section className="flex h-full items-center justify-center rounded-lg border border-dashed border-border bg-elevated p-8 text-sm text-muted">
        Select a session to inspect its working log.
      </section>
    );
  }

  return (
    <section className="flex h-full min-h-0 flex-col rounded-lg border border-border bg-elevated">
      <header className="border-b border-border px-5 py-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className={cn("inline-block h-2 w-2 rounded-full", display?.dotClass)} />
              <h2 className="truncate font-mono text-sm text-foreground">{session.session_id}</h2>
            </div>
            <p className="mt-2 text-sm text-muted">
              {session.primary_thread
                ? `Primary thread: ${session.primary_thread}`
                : "No primary thread selected."}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onEditScope}
              disabled={!canEditScope}
              className={buttonClass("neutral")}
            >
              Scope
            </button>
            <button
              type="button"
              onClick={onBrief}
              disabled={!canEndSession}
              className={buttonClass("accent")}
            >
              Brief
            </button>
            <button
              type="button"
              onClick={onDrop}
              disabled={!canEndSession}
              className={buttonClass("neutral")}
            >
              Drop
            </button>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2 text-xs text-muted">
          <span className={cn("rounded-sm px-2 py-1 font-medium uppercase tracking-wide", display?.textClass)}>
            {display?.label}
          </span>
          <span>Created {formatTimestamp(session.created_at)}</span>
          <span>Turns {session.turn_count}</span>
          <span>Events {events.length}</span>
          <span>{socketState === "live" ? "Live stream connected" : `Live stream ${socketState}`}</span>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          {session.mounted_threads.map((slug) => (
            <span
              key={slug}
              className="rounded-sm border border-border bg-background px-2 py-1 font-mono text-[11px] text-muted"
            >
              {slug}
            </span>
          ))}
        </div>
      </header>

      <div ref={viewportRef} className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
        {error ? (
          <div className="mb-4 rounded-md border border-danger bg-danger-subtle px-3 py-2 text-sm text-danger">
            {error}
          </div>
        ) : null}

        {loading ? (
          <div className="rounded-md border border-border bg-background px-4 py-4 text-sm text-muted">
            Loading session history...
          </div>
        ) : items.length === 0 ? (
          <div className="rounded-md border border-dashed border-border bg-background px-4 py-4 text-sm text-muted">
            No working-log events yet.
          </div>
        ) : (
          <div className="space-y-4">
            {items.map((item) =>
              item.kind === "turn" ? (
                <TurnCard key={item.turnId} turnId={item.turnId} events={item.events} />
              ) : (
                <StandaloneEventCard key={item.event.seq} event={item.event} />
              ),
            )}
          </div>
        )}
      </div>

      <Composer
        onSend={onSend}
        disabled={!canSend}
        placeholder={
          interactive
            ? "Describe the next step, question, or direction for this session..."
            : "Create a new session to continue working."
        }
      />
    </section>
  );
}

function TurnCard({ turnId, events }: { turnId: string; events: SessionEvent[] }) {
  const failed = events.some((event) => event.type === "turn.failed");
  const completed = events.some((event) => event.type === "turn.completed");
  const stateLabel = failed ? "failed" : completed ? "completed" : "running";

  return (
    <article className="rounded-lg border border-border bg-background">
      <header className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div className="flex items-center gap-3">
          <span className="font-mono text-xs text-muted">{turnId}</span>
          <span
            className={cn(
              "rounded-sm px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide",
              failed
                ? "bg-danger-subtle text-danger"
                : completed
                  ? "bg-accent-subtle text-accent"
                  : "bg-panel text-muted",
            )}
          >
            {stateLabel}
          </span>
        </div>
        <span className="text-xs font-mono text-muted">
          {formatTimestamp(events[0]?.ts)}
        </span>
      </header>

      <div className="space-y-3 px-4 py-4">
        {events.map((event) => (
          <EventBody key={event.seq} event={event} />
        ))}
      </div>
    </article>
  );
}

function StandaloneEventCard({ event }: { event: SessionEvent }) {
  return (
    <article className="rounded-md border border-border bg-panel px-4 py-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium text-foreground">{eventSummary(event)}</p>
        <span className="text-xs font-mono text-muted">{formatTimestamp(event.ts)}</span>
      </div>
      <EventMeta event={event} />
    </article>
  );
}

function EventBody({ event }: { event: SessionEvent }) {
  if (event.type === "turn.started" || event.type === "turn.completed" || event.type === "turn.failed") {
    return <EventMeta event={event} compact />;
  }

  if (event.type === "user.message" || event.type === "assistant.message_completed") {
    return <TextEntry event={event} />;
  }

  return (
    <div className="rounded-md border border-border bg-elevated px-3 py-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium text-foreground">{eventSummary(event)}</p>
        <span className="text-xs font-mono text-muted">{formatTimestamp(event.ts)}</span>
      </div>
      <EventMeta event={event} />
      {renderEventDetails(event)}
    </div>
  );
}

function TextEntry({ event }: { event: SessionEvent }) {
  const label = event.type === "user.message" ? "You" : "HaL";
  const accentClass =
    event.type === "user.message"
      ? "border-human bg-human-subtle"
      : "border-accent bg-accent-subtle";
  const text = extractTextBlock(event) ?? "";

  return (
    <section className={cn("rounded-md border px-4 py-3", accentClass)}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <span className="text-xs font-medium uppercase tracking-widest text-foreground">{label}</span>
        <span className="text-xs font-mono text-muted">{formatTimestamp(event.ts)}</span>
      </div>
      <div className="prose prose-mineral max-w-none text-sm">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
      </div>
    </section>
  );
}

function EventMeta({ event, compact = false }: { event: SessionEvent; compact?: boolean }) {
  const refs = Object.entries(event.refs).filter(([, value]) => value != null);
  if (compact && refs.length === 0) return null;

  return (
    <div className={cn("mt-2 flex flex-wrap gap-2 text-[11px] text-muted", compact && "mt-0")}>
      <span className="font-mono">{event.type}</span>
      <span className="font-mono">{event.actor}</span>
      {refs.slice(0, compact ? 2 : 4).map(([key, value]) => (
        <span key={key} className="rounded-sm border border-border bg-background px-1.5 py-0.5">
          {key}: {formatInline(value)}
        </span>
      ))}
    </div>
  );
}

function renderEventDetails(event: SessionEvent) {
  if (event.type === "context.compiled") {
    const mounted = formatInline(event.refs.mounted_threads);
    const recalled = formatInline(event.refs.recalled_threads);
    const tokens = formatInline(event.payload.estimated_input_tokens);
    return (
      <div className="mt-3 grid gap-2 text-xs text-muted md:grid-cols-3">
        <Detail label="Mounted">{mounted}</Detail>
        <Detail label="Recalled">{recalled}</Detail>
        <Detail label="Tokens">{tokens}</Detail>
      </div>
    );
  }

  if (event.type === "tool.call_started" || event.type === "tool.call_completed") {
    const resultPreview =
      typeof event.payload.result_preview === "string" ? event.payload.result_preview : null;
    return (
      <div className="mt-3 space-y-2">
        <Detail label="Args">{formatInline(event.payload.args)}</Detail>
        {resultPreview ? <Detail label="Result">{resultPreview}</Detail> : null}
      </div>
    );
  }

  const text = extractTextBlock(event);
  if (text) {
    return (
      <div className="prose prose-mineral mt-3 max-w-none text-sm">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
      </div>
    );
  }

  return null;
}

function Detail({ label, children }: { label: string; children: string }) {
  return (
    <div className="rounded-sm border border-border bg-background px-2 py-1.5">
      <div className="text-[11px] uppercase tracking-wide text-muted">{label}</div>
      <div className="mt-1 font-mono text-xs text-foreground">{children}</div>
    </div>
  );
}

function formatInline(value: unknown): string {
  if (Array.isArray(value)) {
    return value.join(", ");
  }
  if (typeof value === "object" && value !== null) {
    const json = JSON.stringify(value);
    return json.length > 200 ? `${json.slice(0, 197)}...` : json;
  }
  if (value == null) return "--";
  return String(value);
}

function buttonClass(kind: "accent" | "neutral"): string {
  return cn(
    "rounded-md px-3 py-1.5 text-xs font-medium transition-colors duration-fast ease-standard",
    "disabled:cursor-not-allowed disabled:opacity-50",
    kind === "accent"
      ? "bg-accent text-on-accent hover:brightness-95"
      : "border border-border bg-background text-foreground hover:bg-panel",
  );
}
