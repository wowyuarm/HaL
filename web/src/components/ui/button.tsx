/**
 * Button — Primary interactive primitive.
 *
 * Variants map to the design system's restrained control philosophy:
 * primary actions are rare (accent), most controls are secondary or ghost.
 */

import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  [
    "inline-flex items-center justify-center gap-1.5 rounded-full border",
    "font-medium transition-colors duration-fast ease-standard",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:ring-offset-2 focus-visible:ring-offset-hal-canvas",
    "disabled:cursor-not-allowed disabled:opacity-50",
    "[&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  ],
  {
    variants: {
      variant: {
        primary:
          "border-accent bg-accent text-white shadow-sm hover:brightness-95",
        secondary:
          "border-border bg-[rgba(255,255,255,0.45)] text-hal-primary hover:bg-hal-panel",
        danger: "border-danger bg-danger text-white hover:brightness-95",
        ghost: "border-transparent bg-transparent text-hal-primary hover:border-subtle hover:bg-hal-panel",
      },
      size: {
        sm: "px-3 py-1.5 text-meta",
        md: "px-3.5 py-2 text-body",
        icon: "h-9 w-9 p-0",
      },
    },
    defaultVariants: {
      variant: "primary",
      size: "md",
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, type = "button", ...props }, ref) => (
    <button
      ref={ref}
      type={type}
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  ),
);

Button.displayName = "Button";

export { Button, buttonVariants };
