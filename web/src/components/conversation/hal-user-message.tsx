/**
 * HalUserMessage — renders a user message in HaL's design language.
 *
 * Uses assistant-ui MessagePrimitive for context binding while applying
 * HaL design tokens (human-subtle background, human accent border).
 * Command messages render as compact inline rows without bubble chrome.
 */

import { MessagePrimitive, useMessage } from "@assistant-ui/react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { formatRelativeTime, formatTimestamp } from "@/lib/runtime";
import type { HalMessageMeta } from "@/lib/session-adapter";
import type { TextMessagePartProps } from "@assistant-ui/react";

export function HalUserMessage() {
  const createdAt = useMessage((s) => s.createdAt);
  const custom = useMessage(
    (s) => s.metadata?.custom as HalMessageMeta | undefined,
  );
  const firstText = useMessage((s) => {
    const part = s.content[0];
    return part?.type === "text" ? part.text : "";
  });
  const isCommand = custom?.isCommand === true;
  const ts = createdAt?.toISOString() ?? "";

  // Command messages: compact inline row, no bubble.
  if (isCommand) {
    return (
      <MessagePrimitive.Root className="px-1 py-1">
        <div className="flex items-center justify-between gap-3">
          <div className="flex min-w-0 flex-1 items-center gap-2 text-meta">
            <span className="shrink-0 text-hal-muted">›</span>
            <span className="truncate font-mono text-hal-primary">
              {firstText || "_No content_"}
            </span>
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
    <MessagePrimitive.Root className="rounded-md border border-border border-l-2 border-l-human bg-hal-human-subtle px-4 py-3">
      {ts && (
        <div className="mb-1.5 flex items-center justify-end">
          <span className="text-caption text-hal-muted" title={formatTimestamp(ts)}>
            {formatRelativeTime(ts)}
          </span>
        </div>
      )}
      <MessagePrimitive.Content components={USER_CONTENT_COMPONENTS} />
    </MessagePrimitive.Root>
  );
}

function UserTextPart({ text }: TextMessagePartProps) {
  return (
    <div className="prose prose-mineral max-w-none text-body">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text || "_No content_"}</ReactMarkdown>
    </div>
  );
}

const USER_CONTENT_COMPONENTS = { Text: UserTextPart } as const;
