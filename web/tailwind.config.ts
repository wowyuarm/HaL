import type { Config } from "tailwindcss";
import typography from "@tailwindcss/typography";

const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        background: "var(--bg)",
        panel: "var(--bg-panel)",
        elevated: "var(--bg-elevated)",
        inset: "var(--bg-inset)",

        border: "var(--border)",
        "border-subtle": "var(--border-subtle)",
        "border-accent": "var(--border-accent)",

        foreground: "var(--text)",
        muted: "var(--text-muted)",
        "on-accent": "var(--text-on-accent)",

        accent: "var(--accent)",
        "accent-subtle": "var(--accent-subtle)",
        human: "var(--human)",
        "human-subtle": "var(--human-subtle)",
        danger: "var(--danger)",
        "danger-subtle": "var(--danger-subtle)",
      },
      borderColor: {
        DEFAULT: "var(--border)",
        subtle: "var(--border-subtle)",
        accent: "var(--border-accent)",
      },
      borderRadius: {
        sm: "var(--radius-sm)",
        md: "var(--radius-md)",
        lg: "var(--radius-lg)",
      },
      boxShadow: {
        popover: "0 4px 12px rgba(0, 0, 0, 0.08)",
      },
      fontFamily: {
        sans: ["var(--font-sans)"],
        mono: ["var(--font-mono)"],
      },
      transitionDuration: {
        fast: "var(--duration-fast)",
        normal: "var(--duration-normal)",
      },
      transitionTimingFunction: {
        standard: "ease-out",
      },
      typography: {
        mineral: {
          css: {
            "--tw-prose-body": "var(--text)",
            "--tw-prose-headings": "var(--text)",
            "--tw-prose-links": "var(--accent)",
            "--tw-prose-code": "var(--text)",
            "--tw-prose-pre-bg": "var(--bg-inset)",
          },
        },
      },
    },
  },
  plugins: [typography],
};

export default config;
