/**
 * HalUserMessage — renders a user message in HaL's design language.
 *
 * Uses assistant-ui MessagePrimitive for context binding while applying
 * HaL design tokens (human-subtle background, human accent border).
 */

import { MessagePrimitive, useMessage } from "@assistant-ui/react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { Tag } from "@/components/ui/tag";
import { formatRelativeTime, formatTimestamp } from "@/lib/runtime";
import type { TextMessagePartProps } from "@assistant-ui/react";

export function HalUserMessage() {
  const createdAt = useMessage((s) => s.createdAt);
  const ts = createdAt?.toISOString() ?? "";

  return (
    <MessagePrimitive.Root className="rounded-md border border-border border-l-2 border-l-human bg-hal-human-subtle px-4 py-3.5">
      <div className="mb-2 flex items-center justify-between gap-3">
        <Tag variant="human">You</Tag>
        {ts && (
          <span className="text-caption text-hal-muted" title={formatTimestamp(ts)}>
            {formatRelativeTime(ts)}
          </span>
        )}
      </div>
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
