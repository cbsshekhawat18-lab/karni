/**
 * Tailwind preset for @karni/ui consumers (Tailwind 3, and 4 through @config).
 *
 * Usage (tailwind.config.ts of the consuming app):
 *
 * ```ts
 * import karniPreset from "@karni/ui/tailwind-preset";
 *
 * export default {
 *   presets: [karniPreset],
 *   content: [
 *     "./src/**\/*.{ts,tsx}",
 *     "./node_modules/@karni/ui/dist/**\/*.js",
 *   ],
 * };
 * ```
 *
 * Also import "@karni/ui/styles.css" once (it defines the --karni-* tokens).
 * Tailwind v4 loads the same config through `@config` in CSS, next to
 * `@import "@karni/ui/tailwind-v4.css"` (see the README).
 */
import type { Config } from "tailwindcss";

const karniPreset = {
  // `as const` keeps the literal type so the preset stays assignable to
  // Config["presets"] when consumers spread it into their own config.
  darkMode: "class" as const,
  theme: {
    extend: {
      colors: {
        background: "hsl(var(--karni-background) / <alpha-value>)",
        foreground: "hsl(var(--karni-foreground) / <alpha-value>)",
        card: {
          DEFAULT: "hsl(var(--karni-card) / <alpha-value>)",
          foreground: "hsl(var(--karni-card-foreground) / <alpha-value>)",
        },
        popover: {
          DEFAULT: "hsl(var(--karni-popover) / <alpha-value>)",
          foreground: "hsl(var(--karni-popover-foreground) / <alpha-value>)",
        },
        primary: {
          DEFAULT: "hsl(var(--karni-primary) / <alpha-value>)",
          foreground: "hsl(var(--karni-primary-foreground) / <alpha-value>)",
        },
        secondary: {
          DEFAULT: "hsl(var(--karni-secondary) / <alpha-value>)",
          foreground: "hsl(var(--karni-secondary-foreground) / <alpha-value>)",
        },
        muted: {
          DEFAULT: "hsl(var(--karni-muted) / <alpha-value>)",
          foreground: "hsl(var(--karni-muted-foreground) / <alpha-value>)",
        },
        accent: {
          DEFAULT: "hsl(var(--karni-accent) / <alpha-value>)",
          foreground: "hsl(var(--karni-accent-foreground) / <alpha-value>)",
        },
        destructive: {
          DEFAULT: "hsl(var(--karni-destructive) / <alpha-value>)",
          foreground: "hsl(var(--karni-destructive-foreground) / <alpha-value>)",
        },
        border: "hsl(var(--karni-border) / <alpha-value>)",
        input: "hsl(var(--karni-input) / <alpha-value>)",
        ring: "hsl(var(--karni-ring) / <alpha-value>)",
        chart: {
          "1": "hsl(var(--karni-chart-1) / <alpha-value>)",
          "2": "hsl(var(--karni-chart-2) / <alpha-value>)",
          "3": "hsl(var(--karni-chart-3) / <alpha-value>)",
          "4": "hsl(var(--karni-chart-4) / <alpha-value>)",
          "5": "hsl(var(--karni-chart-5) / <alpha-value>)",
        },
      },
      borderColor: {
        // A bare `border` class uses the token, never Tailwind's default gray.
        DEFAULT: "hsl(var(--karni-border) / <alpha-value>)",
      },
      borderRadius: {
        lg: "var(--karni-radius)",
        md: "calc(var(--karni-radius) - 2px)",
        sm: "calc(var(--karni-radius) - 4px)",
      },
    },
  },
} satisfies Omit<Config, "content">;

export default karniPreset;
