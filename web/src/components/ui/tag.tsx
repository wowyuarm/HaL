/**
 * Tag — Compact metadata label for categorization.
 *
 * Used for thread tags, event type labels, and other inline metadata.
 * Intentionally small (caption size) and low-contrast by default.
 */

import type { HTMLAttributes, ReactNode } from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const tagVariants = cva(
  "inline-flex items-center rounded-full border px-2 py-1 text-caption font-medium uppercase tracking-[0.1em]",
  {
    variants: {
      variant: {
        default: "border-subtle bg-hal-panel text-hal-muted",
        accent: "border-accent bg-accent-subtle text-accent",
        human: "border-human bg-human-subtle text-human",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export interface TagProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof tagVariants> {
  children: ReactNode;
}

export function Tag({ children, className, variant, ...props }: TagProps) {
  return (
    <span className={cn(tagVariants({ variant }), className)} {...props}>
      {children}
    </span>
  );
}

export { tagVariants };
