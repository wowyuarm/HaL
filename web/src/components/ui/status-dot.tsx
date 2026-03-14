/**
 * StatusDot — Tiny colored circle indicating operational state.
 *
 * Following the design system's expression order, dots are the
 * lightest-weight state indicator (level 1 before badges or fills).
 */

import type { HTMLAttributes } from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const statusDotVariants = cva("inline-block h-2 w-2 shrink-0 rounded-full", {
  variants: {
    state: {
      live: "bg-accent animate-pulse",
      success: "bg-success",
      warning: "bg-warning",
      danger: "bg-danger",
      idle: "bg-accent",
      muted: "bg-hal-muted opacity-60",
    },
  },
  defaultVariants: {
    state: "muted",
  },
});

export interface StatusDotProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof statusDotVariants> {}

export function StatusDot({ className, state, ...props }: StatusDotProps) {
  return (
    <span
      aria-hidden="true"
      className={cn(statusDotVariants({ state }), className)}
      {...props}
    />
  );
}

export { statusDotVariants };
