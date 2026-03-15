import type { ReactNode } from "react";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";

interface SideSheetProps {
  open: boolean;
  title: string;
  description?: string | null;
  meta?: ReactNode;
  widthClassName?: string;
  zIndexClassName?: string;
  onClose?: () => void;
  children: ReactNode;
}

export function SideSheet({
  open,
  title,
  description,
  meta,
  widthClassName = "w-[min(440px,36vw)]",
  zIndexClassName = "z-20",
  onClose,
  children,
}: SideSheetProps) {
  return (
    <aside
      className={cn(
        "absolute inset-y-0 right-0 hidden overflow-hidden px-3 py-5 transition-[opacity,transform] duration-slow ease-standard lg:block motion-reduce:transition-none",
        widthClassName,
        zIndexClassName,
        open
          ? "pointer-events-auto translate-x-0 opacity-100"
          : "pointer-events-none translate-x-4 opacity-0",
      )}
      aria-hidden={!open}
    >
      <div
        className={cn(
          "hal-paper hal-sheet flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-border shadow-popover transition-[opacity,transform,filter] duration-slow ease-standard motion-reduce:transition-none",
          open ? "translate-x-0 opacity-100 blur-0" : "translate-x-3 opacity-0 blur-[2px]",
        )}
      >
        <div className="flex shrink-0 items-start justify-between gap-4 border-b border-subtle px-5 py-4">
          <div className="min-w-0">
            <p className="hal-rule-label">{title}</p>
            {description && <p className="mt-2 max-w-md text-meta text-hal-muted">{description}</p>}
            {meta ? <div className="mt-2">{meta}</div> : null}
          </div>
          {onClose ? (
            <button
              type="button"
              onClick={onClose}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-hal-muted transition-colors hover:text-hal-primary"
              aria-label={`Close ${title.toLowerCase()}`}
            >
              <X className="h-4 w-4" />
            </button>
          ) : null}
        </div>

        <div className="hal-side-sheet-body hal-scroll-hidden min-h-0 flex-1 px-5 py-5 md:px-6 md:py-6">
          {children}
        </div>
      </div>
    </aside>
  );
}
