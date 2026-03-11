/**
 * assistant-ui ExternalStoreRuntime adapter.
 *
 * Bridges the Zustand store and WebSocket transport into assistant-ui's
 * `useExternalStoreRuntime`, giving us scroll management and composability
 * primitives while our store owns the data.
 *
 * Usage (inside a component that also calls `useWebSocket`):
 *
 *   const { send } = useWebSocket();
 *   const runtime = useHalRuntime(send);
 *   return <AssistantRuntimeProvider runtime={runtime}>...</AssistantRuntimeProvider>;
 */
import { useMemo } from "react";
import {
  useExternalStoreRuntime,
  type AppendMessage,
  type ExternalStoreAdapter,
  type ThreadMessageLike,
} from "@assistant-ui/react";

import { useHalStore } from "@/lib/store";
import type { ClientEnvelope } from "@/lib/store";
import type { Message, ToolCall } from "@/lib/types";

// ---------------------------------------------------------------------------
// Message conversion (HaL Message → assistant-ui ThreadMessageLike)
// ---------------------------------------------------------------------------

/** Subset of ThreadMessageLike["content"] array element types we produce. */
type ContentPart =
  | { readonly type: "text"; readonly text: string }
  | {
      readonly type: "tool-call";
      readonly toolCallId: string;
      readonly toolName: string;
      readonly args?: Readonly<Record<string, string>>;
      readonly result?: string;
      readonly isError?: boolean;
    };

/**
 * Map a HaL ToolCall (wire format) into an assistant-ui tool-call content
 * part.
 *
 * `args_summary` describes the tool *input* (e.g. "auth.py"), so it is
 * carried as `args` context.  On failure, `error` becomes the `result`.
 */
function toolCallToPart(tc: ToolCall): ContentPart {
  return {
    type: "tool-call",
    toolCallId: tc.id,
    toolName: tc.name,
    args: { summary: tc.args_summary },
    ...(tc.status === "failed"
      ? { result: tc.error ?? "Tool call failed.", isError: true }
      : {}),
  };
}

/**
 * Convert a HaL `Message` into assistant-ui's `ThreadMessageLike`.
 *
 * - User messages: plain text content.
 * - Assistant messages: text + optional tool-call parts from metadata.
 */
function convertMessage(msg: Message): ThreadMessageLike {
  const toolCalls = msg.metadata?.tool_calls;

  // Fast path: no tool calls → return content as a plain string.
  if (!toolCalls || toolCalls.length === 0) {
    return {
      id: msg.id,
      role: msg.role,
      content: msg.content,
      createdAt: new Date(msg.ts),
    };
  }

  // Build a content-parts array with text + tool calls.
  const parts: ContentPart[] = [];

  if (msg.content.length > 0) {
    parts.push({ type: "text", text: msg.content });
  }

  for (const tc of toolCalls) {
    parts.push(toolCallToPart(tc));
  }

  return {
    id: msg.id,
    role: msg.role,
    content: parts,
    createdAt: new Date(msg.ts),
  };
}

// ---------------------------------------------------------------------------
// Outbound: extract text from an AppendMessage
// ---------------------------------------------------------------------------

/**
 * Extract the plain-text content from an assistant-ui `AppendMessage`.
 *
 * AppendMessage.content is an array of typed parts; we concatenate all text
 * parts and trim the result.
 */
function extractText(append: AppendMessage): string {
  return append.content
    .filter(
      (part): part is Extract<(typeof append.content)[number], { type: "text" }> =>
        part.type === "text",
    )
    .map((part) => part.text)
    .join("\n\n")
    .trim();
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * Build an assistant-ui runtime backed by the HaL store and WebSocket.
 *
 * @param send - The `send` function from `useWebSocket()`. Passed explicitly
 *   so that the WebSocket lifecycle is owned by a single call site (the app
 *   root), not duplicated per consumer.
 */
export function useHalRuntime(send: (data: ClientEnvelope) => boolean) {
  const messages = useHalStore((s) => s.messages);
  const status = useHalStore((s) => s.status);
  const addUserMessage = useHalStore((s) => s.addUserMessage);
  const handleError = useHalStore((s) => s.handleError);

  const adapter = useMemo<ExternalStoreAdapter<Message>>(
    () => ({
      messages,
      isRunning: status === "processing",
      convertMessage,

      onNew: async (append: AppendMessage) => {
        const text = extractText(append);
        if (!text) return;

        const ok = send({ type: "message", content: text });
        if (!ok) {
          const error = "Cannot send: WebSocket is not connected.";
          handleError(error);
          throw new Error(error);
        }

        // Optimistic local insert after confirming the socket accepted the
        // frame.  The server does not currently echo user messages back, so
        // this is the only source of the user turn in the message list.
        // If a future protocol revision adds server echo, `upsertMessage`
        // in the store will reconcile by ID.
        addUserMessage(text);
      },
    }),
    [messages, status, addUserMessage, handleError, send],
  );

  return useExternalStoreRuntime(adapter);
}
