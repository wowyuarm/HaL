/**
 * MessageList — Scrollable conversation container with auto-scroll.
 *
 * Renders messages in a max-w-3xl centered column with border-subtle
 * dividers. Auto-scrolls to bottom when new messages arrive, but only
 * if the user is already near the bottom (within a threshold).
 */

import { useEffect, useRef } from "react";

import type { Message as MessageType } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Message } from "./message";

/** Distance from bottom (px) within which auto-scroll is active. */
const SCROLL_THRESHOLD = 120;

interface MessageListProps {
  messages: MessageType[];
  className?: string;
}

export function MessageList({ messages, className }: MessageListProps) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const wasNearBottomRef = useRef(true);

  // Track whether user is near the bottom before render.
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;

    const handleScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = viewport;
      wasNearBottomRef.current = scrollHeight - scrollTop - clientHeight < SCROLL_THRESHOLD;
    };

    viewport.addEventListener("scroll", handleScroll, { passive: true });
    return () => viewport.removeEventListener("scroll", handleScroll);
  }, []);

  // Auto-scroll to bottom on new messages (only if near bottom).
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport || !wasNearBottomRef.current) return;

    viewport.scrollTop = viewport.scrollHeight;
  }, [messages]);

  return (
    <div ref={viewportRef} className={cn("flex-1 overflow-y-auto px-5 py-6", className)}>
      <div className="mx-auto max-w-3xl">
        {messages.length === 0 ? (
          <p className="text-sm text-muted">Messages will appear here.</p>
        ) : (
          <div className="divide-y divide-border-subtle">
            {messages.map((msg) => (
              <Message key={msg.id} message={msg} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
