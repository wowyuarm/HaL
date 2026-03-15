import type { Config } from "tailwindcss";
import typography from "@tailwindcss/typography";

const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        /* ── New semantic namespace (bg-hal-canvas, text-hal-primary, etc.) ── */
        hal: {
          canvas: "var(--hal-canvas)",
          panel: "var(--hal-panel)",
          paper: "var(--hal-paper)",
          veil: "var(--hal-veil)",
          float: "var(--hal-float)",
          inset: "var(--hal-inset)",
          primary: "var(--hal-text)",
          muted: "var(--hal-text-muted)",
          live: "var(--hal-live)",
          "live-subtle": "var(--hal-live-subtle)",
          success: "var(--hal-success)",
          "success-subtle": "var(--hal-success-subtle)",
          warning: "var(--hal-warning)",
          "warning-subtle": "var(--hal-warning-subtle)",
          human: "var(--hal-human)",
          "human-subtle": "var(--hal-human-subtle)",
          danger: "var(--hal-danger)",
          "danger-subtle": "var(--hal-danger-subtle)",
        },

        /* ── Standalone semantic colors ── */
        border: "var(--border-default)",
        success: "var(--color-success)",
        "success-subtle": "var(--color-success-subtle)",
        warning: "var(--color-warning)",
        "warning-subtle": "var(--color-warning-subtle)",
        danger: "var(--color-danger)",
        "danger-subtle": "var(--color-danger-subtle)",
        human: "var(--color-human)",
        "human-subtle": "var(--color-human-subtle)",
        accent: "var(--color-accent)",
        "accent-subtle": "var(--color-accent-subtle)",
      },
      borderColor: {
        DEFAULT: "var(--border-default)",
        subtle: "var(--border-subtle)",
        strong: "var(--border-strong)",
        accent: "var(--border-accent)",
        human: "var(--border-human)",
        danger: "var(--border-danger)",
        success: "var(--border-success)",
        warning: "var(--border-warning)",
      },
      borderRadius: {
        sm: "var(--radius-sm)",
        md: "var(--radius-md)",
        lg: "var(--radius-lg)",
      },
      boxShadow: {
        sm: "var(--shadow-sm)",
        popover: "var(--shadow-popover)",
      },
      fontSize: {
        title: [
          "var(--type-title-size)",
          { lineHeight: "var(--type-title-line)", fontWeight: "var(--type-title-weight)" },
        ],
        heading: [
          "var(--type-heading-size)",
          { lineHeight: "var(--type-heading-line)", fontWeight: "var(--type-heading-weight)" },
        ],
        subheading: [
          "var(--type-subheading-size)",
          {
            lineHeight: "var(--type-subheading-line)",
            fontWeight: "var(--type-subheading-weight)",
          },
        ],
        body: [
          "var(--type-body-size)",
          { lineHeight: "var(--type-body-line)", fontWeight: "var(--type-body-weight)" },
        ],
        reading: [
          "var(--type-reading-size)",
          { lineHeight: "var(--type-reading-line)", fontWeight: "var(--type-reading-weight)" },
        ],
        meta: [
          "var(--type-meta-size)",
          { lineHeight: "var(--type-meta-line)", fontWeight: "var(--type-meta-weight)" },
        ],
        caption: [
          "var(--type-caption-size)",
          { lineHeight: "var(--type-caption-line)", fontWeight: "var(--type-caption-weight)" },
        ],
      },
      fontFamily: {
        sans: ["var(--font-sans)"],
        serif: ["var(--font-serif)"],
        mono: ["var(--font-mono)"],
      },
      transitionDuration: {
        fast: "var(--duration-fast)",
        normal: "var(--duration-normal)",
        slow: "var(--duration-slow)",
      },
      transitionTimingFunction: {
        standard: "var(--ease-standard)",
      },
      typography: {
        mineral: {
          css: {
            "--tw-prose-body": "var(--hal-text)",
            "--tw-prose-headings": "var(--hal-text)",
            "--tw-prose-links": "var(--hal-live)",
            "--tw-prose-code": "var(--hal-text)",
            "--tw-prose-bold": "var(--hal-text)",
            "--tw-prose-bullets": "rgba(74, 122, 116, 0.48)",
            "--tw-prose-hr": "var(--border-subtle)",
            "--tw-prose-quotes": "var(--hal-text)",
            "--tw-prose-pre-bg": "var(--hal-inset)",
            h1: {
              fontFamily: "var(--font-serif)",
              fontWeight: "600",
              letterSpacing: "-0.02em",
            },
            h2: {
              fontFamily: "var(--font-serif)",
              fontWeight: "600",
              letterSpacing: "-0.015em",
            },
            h3: {
              fontFamily: "var(--font-serif)",
              fontWeight: "600",
            },
            p: {
              lineHeight: "1.8",
            },
            code: {
              borderRadius: "999px",
              backgroundColor: "rgba(36, 33, 29, 0.05)",
              padding: "0.18rem 0.48rem",
              fontWeight: "500",
            },
            pre: {
              border: "1px solid var(--border-subtle)",
              borderRadius: "14px",
            },
            blockquote: {
              borderLeft: "2px solid var(--border-accent)",
              color: "var(--hal-text-muted)",
              fontStyle: "normal",
            },
          },
        },
      },
    },
  },
  plugins: [typography],
};

export default config;
