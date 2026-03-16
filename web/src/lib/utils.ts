import { type ClassValue, clsx } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/**
 * Custom tailwind-merge that recognises the design system's typography
 * utilities (text-body, text-meta, etc.) as font-size classes — not
 * text-color.  Without this, twMerge silently drops color utilities
 * like text-hal-on-accent when they appear alongside text-body.
 */
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": [
        {
          text: [
            "title",
            "heading",
            "subheading",
            "body",
            "reading",
            "meta",
            "caption",
          ],
        },
      ],
    },
  },
});

/** Merge Tailwind classes with conflict resolution. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
