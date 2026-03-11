/** Tool execution state as reported by the engine. */
export type ToolCallStatus = "completed" | "failed" | "running";

/** Single tool call record attached to a message. */
export interface ToolCall {
  id: string;
  name: string;
  args_summary: string;
  status: ToolCallStatus;
  /** Present only when status is "failed". */
  error?: string;
}

/** Optional metadata carried by assistant messages. */
export interface MessageMetadata {
  tool_calls?: ToolCall[];
}

/** Chat message role. */
export type MessageRole = "user" | "assistant";

/** Single chat message in a conversation. */
export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  /** ISO 8601 timestamp. */
  ts: string;
  metadata?: MessageMetadata;
}

/** Sidebar thread entry. */
export interface Thread {
  slug: string;
  name: string;
  scope: string;
  /** ISO 8601 timestamp of last activity. */
  last_active: string;
}

/** Compact context summary for the sidebar panel. */
export interface ContextSummaryData {
  tokens: number;
  tools: number;
  history: number;
}
