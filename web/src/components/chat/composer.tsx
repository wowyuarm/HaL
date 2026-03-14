/**
 * Composer — Message input area with auto-grow and enter-to-send.
 *
 * Manages its own input state internally. Calls onSend(content) when
 * the user presses Enter (without Shift) or clicks the Send button.
 * Textarea auto-grows from MIN_ROWS to MAX_ROWS based on content.
 */

import { useCallback, useLayoutEffect, useRef, useState } from "react";
import { SendHorizontal } from "lucide-react";

import { cn } from "@/lib/utils";

/** Textarea row limits for auto-grow behavior. */
const MIN_ROWS = 2;
const MAX_ROWS = 8;

interface ComposerProps {
  onSend: (content: string) => void;
  disabled?: boolean;
  className?: string;
  placeholder?: string;
}

export function Composer({
  onSend,
  disabled = false,
  className,
  placeholder = "Type your next step...",
}: ComposerProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const canSend = !disabled && value.trim().length > 0;

  const handleSend = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;

    onSend(trimmed);
    setValue("");
  }, [value, disabled, onSend]);

  // Auto-grow textarea height based on content.
  useLayoutEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    // Reset to measure natural scroll height.
    textarea.style.height = "0px";

    const style = window.getComputedStyle(textarea);
    const lineHeight = parseFloat(style.lineHeight) || 20;
    const paddingY = parseFloat(style.paddingTop) + parseFloat(style.paddingBottom);

    const minHeight = lineHeight * MIN_ROWS + paddingY;
    const maxHeight = lineHeight * MAX_ROWS + paddingY;
    const nextHeight = Math.min(Math.max(textarea.scrollHeight, minHeight), maxHeight);

    textarea.style.height = `${nextHeight}px`;
    textarea.style.overflowY = textarea.scrollHeight > maxHeight ? "auto" : "hidden";
  }, [value]);

  return (
    <div className={cn("shrink-0 border-t border-subtle px-3 py-3 md:px-4 md:py-4", className)}>
      <div className="hal-paper mx-auto max-w-5xl rounded-[22px] border border-border p-3 shadow-sm md:p-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-end">
          <div className="flex-1 rounded-[18px] border border-subtle bg-hal-inset px-4 py-3">
            <textarea
              ref={textareaRef}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  if (canSend) handleSend();
                }
              }}
              disabled={disabled}
              rows={MIN_ROWS}
              placeholder={placeholder}
              className="w-full resize-none bg-transparent text-body leading-7 text-hal-primary outline-none placeholder:text-hal-muted disabled:cursor-not-allowed disabled:opacity-60"
            />
            <div className="mt-3 flex items-center justify-between gap-3 border-t border-subtle pt-2.5 text-caption text-hal-muted">
              <span>Enter sends. Shift+Enter adds a newline.</span>
              <span>{value.trim() ? `${value.trim().length} chars` : "Human directs, HaL executes."}</span>
            </div>
          </div>

          <button
            type="button"
            disabled={!canSend}
            onClick={handleSend}
            className={cn(
              "inline-flex h-11 w-11 shrink-0 items-center justify-center self-end rounded-full border shadow-sm transition-colors duration-fast ease-standard",
              canSend
                ? "border-accent bg-accent text-white hover:brightness-95"
                : "border-subtle bg-hal-float text-hal-muted",
              "disabled:cursor-not-allowed disabled:opacity-50",
            )}
            aria-label="Send message"
          >
            <SendHorizontal className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
