/**
 * Message — Single chat message rendered in Document Flow style.
 *
 * User messages: undecorated, left-aligned, "You" label + muted timestamp.
 * HaL messages: 2px accent left border, accent-subtle background,
 *               "HaL" label + muted timestamp, markdown body, tool calls.
 */

import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";

import type { Message as MessageType } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ToolCalls } from "./tool-calls";

interface MessageProps {
  message: MessageType;
  className?: string;
}

export function Message({ message, className }: MessageProps) {
  const isAssistant = message.role === "assistant";
  const toolCalls = message.metadata?.tool_calls ?? [];

  return (
    <article
      className={cn(
        "py-5",
        isAssistant && "border-l-2 border-accent bg-accent-subtle pl-4 pr-2",
        className,
      )}
    >
      {/* Author + timestamp header */}
      <header className="mb-2 flex items-baseline justify-between">
        <span
          className={cn(
            "text-xs font-medium uppercase tracking-widest",
            isAssistant ? "text-accent" : "text-muted",
          )}
        >
          {isAssistant ? "HaL" : "You"}
        </span>
        <time
          className="text-xs font-mono tabular-nums text-muted"
          dateTime={message.ts}
        >
          {formatTimestamp(message.ts)}
        </time>
      </header>

      {/* Markdown content */}
      <div
        className={cn(
          "min-w-0",
          "prose prose-mineral max-w-none text-sm",
          "prose-headings:mb-3 prose-headings:mt-5",
          "prose-p:my-2 prose-p:leading-relaxed",
          "prose-pre:rounded-md prose-pre:border prose-pre:border-subtle prose-pre:bg-inset",
          "prose-code:rounded-sm prose-code:bg-inset prose-code:px-1 prose-code:py-0.5 prose-code:font-mono prose-code:text-[0.85em]",
          "prose-a:text-accent hover:prose-a:underline",
        )}
      >
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          rehypePlugins={[rehypeHighlight]}
        >
          {message.content}
        </ReactMarkdown>

        {/* Tool calls (assistant messages only) */}
        {toolCalls.length > 0 && <ToolCalls toolCalls={toolCalls} />}
      </div>
    </article>
  );
}

/**
 * Format an ISO timestamp for display.
 * Shows "HH:MM" for today, "Mon DD, HH:MM" otherwise.
 * Falls back to the raw string on invalid input.
 */
function formatTimestamp(ts: string): string {
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return ts;

  const now = new Date();
  const isToday =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate();

  if (isToday) {
    return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  }

  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
