/**
 * Panel — Surface container with configurable elevation.
 *
 * Maps directly to the design system's four surface levels:
 * base (canvas), raised (panel), elevated (float + shadow), inset.
 */

import type { HTMLAttributes, ReactNode } from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const panelVariants = cva("rounded-md", {
  variants: {
    surface: {
      base: "bg-hal-canvas",
      raised: "bg-hal-panel",
      elevated: "bg-hal-float shadow-sm",
      inset: "bg-hal-inset",
    },
    border: {
      true: "border border-border",
      false: "",
    },
  },
  defaultVariants: {
    surface: "base",
    border: false,
  },
});

export interface PanelProps
  extends HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof panelVariants> {
  children?: ReactNode;
}

export function Panel({ className, surface, border, children, ...props }: PanelProps) {
  // Default border to true for raised and elevated surfaces.
  const resolvedBorder =
    border ?? (surface === "raised" || surface === "elevated" ? true : false);

  return (
    <div
      className={cn(panelVariants({ surface, border: resolvedBorder }), className)}
      {...props}
    >
      {children}
    </div>
  );
}

export { panelVariants };
