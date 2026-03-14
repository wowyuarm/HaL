/**
 * StatusBadge — Compact status indicator with a text label.
 *
 * Expression level 3 in the design system's escalation order:
 * dot -> inline label -> badge -> border tint -> fill -> banner.
 */

import type { HTMLAttributes, ReactNode } from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const statusBadgeVariants = cva(
  "inline-flex items-center rounded-full border px-2 py-1 text-caption font-semibold uppercase tracking-[0.12em]",
  {
    variants: {
      state: {
        live: "border-accent bg-accent-subtle text-accent",
        success: "border-success bg-success-subtle text-success",
        warning: "border-warning bg-warning-subtle text-warning",
        danger: "border-danger bg-danger-subtle text-danger",
        muted: "border-subtle bg-hal-panel text-hal-muted",
      },
    },
    defaultVariants: {
      state: "muted",
    },
  },
);

export interface StatusBadgeProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof statusBadgeVariants> {
  children: ReactNode;
}

export function StatusBadge({
  children,
  className,
  state,
  ...props
}: StatusBadgeProps) {
  return (
    <span
      className={cn(statusBadgeVariants({ state }), className)}
      {...props}
    >
      {children}
    </span>
  );
}

export { statusBadgeVariants };
