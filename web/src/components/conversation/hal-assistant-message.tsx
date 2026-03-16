/**
 * HalAssistantMessage — renders an assistant message with tool call parts.
 *
 * Uses assistant-ui primitives for context binding. Tool calls render as
 * compact rows. Text parts render as markdown with prose-mineral styling.
 * Command responses render as compact inline rows without bubble chrome.
 */

import { MessagePrimitive, useMessage } from "@assistant-ui/react";
import type { TextMessagePartProps, ToolCallMessagePartProps } from "@assistant-ui/react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { StatusDot } from "@/components/ui/status-dot";
import { summarizeEvidenceKinds } from "@/lib/evidence";
import { formatRelativeTime, formatTimestamp } from "@/lib/runtime";
import type { HalMessageMeta } from "@/lib/session-adapter";
import { useHalStore } from "@/lib/store";

export function HalAssistantMessage() {
  const createdAt = useMessage((s) => s.createdAt);
  const isRunning = useMessage((s) => s.status?.type === "running");
  const isFailed = useMessage((s) => s.status?.type === "incomplete");
  const custom = useMessage(
    (s) => s.metadata?.custom as HalMessageMeta | undefined,
  );
  const firstText = useMessage((s) => {
    const part = s.content.find((item) => item.type === "text");
    return part?.type === "text" ? part.text : "";
  });
  const openInspector = useHalStore((s) => s.openInspector);
  const ts = createdAt?.toISOString() ?? "";
  const isCommand = custom?.isCommand === true;

  const evidenceCounts = custom?.evidenceCounts;
  const totalEvidence = evidenceCounts
    ? Object.values(evidenceCounts).reduce((a, b) => a + b, 0)
    : 0;

  // Command responses: compact inline row, no bubble.
  if (isCommand) {
    const commandText = isFailed ? summarizeErrorText(firstText) : firstText;
    return (
      <MessagePrimitive.Root className="px-1 py-1">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 flex-1 items-center gap-2">
            {isRunning && <StatusDot state="live" />}
            {commandText && (
              <span className={isFailed ? "text-meta text-danger" : "text-meta text-hal-primary"}>
                {commandText}
              </span>
            )}
          </div>
          {ts && (
            <span className="shrink-0 text-caption text-hal-muted" title={formatTimestamp(ts)}>
              {formatRelativeTime(ts)}
            </span>
          )}
        </div>
      </MessagePrimitive.Root>
    );
  }

  return (
    <MessagePrimitive.Root
      className={
        isFailed
          ? "rounded-md border border-danger bg-hal-danger-subtle px-4 py-3"
          : "rounded-md border border-border border-l-2 border-l-accent bg-hal-panel px-4 py-3"
      }
    >
      <div className="mb-1.5 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          {isRunning && <StatusDot state="live" />}
          {custom?.origin === "background_resume" && (
            <span className="text-caption font-medium uppercase tracking-[0.1em] text-hal-muted">
              background
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {ts && (
            <span className="text-caption text-hal-muted" title={formatTimestamp(ts)}>
              {formatRelativeTime(ts)}
            </span>
          )}
        </div>
      </div>

      <MessagePrimitive.Content components={ASSISTANT_CONTENT_COMPONENTS} />

      {totalEvidence > 0 && custom?.turnId && evidenceCounts && (
        <button
          type="button"
          onClick={() => openInspector(custom.turnId!)}
          className="group mt-3 flex w-full items-stretch overflow-hidden rounded-md border border-subtle bg-hal-paper text-left transition-all duration-fast ease-standard hover:border-accent hover:bg-hal-hover"
        >
          <span className="w-[3px] shrink-0 bg-[color:var(--turn-seam-color)] transition-colors duration-fast ease-standard group-hover:bg-[color:var(--turn-seam-active)]" />
          <span className="flex min-w-0 flex-1 items-center justify-between gap-3 px-3 py-2.5">
            <span className="min-w-0">
              <span className="hal-meta-kicker">Evidence</span>
              <span className="mt-1 block truncate text-meta text-hal-primary">
                {summarizeEvidenceKinds(evidenceCounts)}
              </span>
            </span>
            <span className="shrink-0 text-caption text-hal-muted">
              {totalEvidence} record{totalEvidence === 1 ? "" : "s"}
            </span>
          </span>
        </button>
      )}
    </MessagePrimitive.Root>
  );
}

function AssistantTextPart({ text }: TextMessagePartProps) {
  if (!text?.trim()) return null;

  return (
    <div className="prose prose-mineral max-w-none text-body">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  );
}

function HalToolCallPart({ toolName, result, isError }: ToolCallMessagePartProps) {
  const dotState = isError ? "danger" : "success";
  const brief = typeof result === "string" ? truncate(result, 100) : "completed";

  return (
    <div className="my-1.5 flex items-center gap-2 rounded-md border border-subtle bg-hal-paper px-3 py-2">
      <StatusDot state={dotState} />
      <span className="font-mono text-meta text-hal-primary">{toolName}</span>
      <span className="min-w-0 flex-1 truncate text-meta text-hal-muted">{brief}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Error text helpers
// ---------------------------------------------------------------------------

function summarizeErrorText(text: string): string {
  const jsonMessage = extractJsonMessage(text);
  return truncate((jsonMessage ?? text).replace(/\s+/g, " ").trim(), 180);
}

function extractJsonMessage(text: string): string | null {
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start === -1 || end <= start) return null;

  try {
    const parsed = JSON.parse(text.slice(start, end + 1)) as unknown;
    if (!parsed || typeof parsed !== "object") return null;
    const obj = parsed as Record<string, unknown>;
    // Try common error shape: { error: { message: "..." } } or { message: "..." }
    if (typeof obj.message === "string") return obj.message;
    if (obj.error && typeof obj.error === "object") {
      const inner = obj.error as Record<string, unknown>;
      if (typeof inner.message === "string") return inner.message;
    }
    return null;
  } catch {
    return null;
  }
}

function truncate(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 3)}...`;
}

const ASSISTANT_CONTENT_COMPONENTS = {
  Text: AssistantTextPart,
  tools: { Fallback: HalToolCallPart },
} as const;
