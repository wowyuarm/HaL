/**
 * HalComposer — message input using assistant-ui ComposerPrimitive.
 *
 * Styled with HaL design tokens. Replaces the custom composer.tsx.
 * The ComposerPrimitive automatically handles send/cancel state
 * through the ExternalStoreRuntime.
 */

import { ComposerPrimitive } from "@assistant-ui/react";

import { HAL_READING_COLUMN_CLASS, halPaperObjectVariants } from "@/components/ui/hal-patterns";
import { cn } from "@/lib/utils";

export function HalComposer() {
  return (
    <ComposerPrimitive.Root className={cn(HAL_READING_COLUMN_CLASS, "shrink-0 px-3 pb-4 pt-2 md:px-5")}>
      <div
        className={cn(
          "hal-paper flex items-end gap-2 shadow-sm",
          halPaperObjectVariants({ surface: "panel", density: "comfortable" }),
        )}
      >
        <ComposerPrimitive.Input
          autoFocus
          placeholder="Describe the next step, question, or direction for this session..."
          className="min-h-[34px] max-h-[200px] flex-1 resize-none border-0 bg-transparent text-body text-hal-primary placeholder:text-hal-muted focus:outline-none"
          rows={1}
        />
        <ComposerPrimitive.Send className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent text-white transition-colors duration-fast ease-standard hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
            className="h-4 w-4"
          >
            <path d="m5 12 7-7 7 7" />
            <path d="M12 19V5" />
          </svg>
        </ComposerPrimitive.Send>
      </div>
    </ComposerPrimitive.Root>
  );
}
