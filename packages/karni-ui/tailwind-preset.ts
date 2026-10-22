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

/**
 * A colour token as a Tailwind colour. Wrapping it in color-mix with
 * `<alpha-value>` keeps opacity modifiers (`bg-primary/50`) working in
 * Tailwind 3 as well as 4, for any colour format the token holds.
 */
function color(name: string): string {
  return `color-mix(in srgb, var(--karni-color-${name}) calc(<alpha-value> * 100%), transparent)`;
}

/** The spacing scale: each step reads --karni-space-<n>, else n × --karni-space-unit. */
export const SPACE_STEPS = [
  0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 16, 20, 24, 28, 32, 36, 40, 44, 48,
  52, 56, 60, 64, 72, 80, 96, 128,
] as const;

function spacing(): Record<string, string> {
  const scale: Record<string, string> = {
    0: "0px",
    px: "var(--karni-space-px, 1px)",
  };
  for (const step of SPACE_STEPS) {
    const name = String(step).replace(".", "-");
    scale[String(step)] =
      `var(--karni-space-${name}, calc(var(--karni-space-unit, 0.25rem) * ${step}))`;
  }
  return scale;
}

const FONT_SIZES = {
  xs: ["0.75rem", "1rem"],
  sm: ["0.875rem", "1.25rem"],
  base: ["1rem", "1.5rem"],
  lg: ["1.125rem", "1.75rem"],
  xl: ["1.25rem", "1.75rem"],
  "2xl": ["1.5rem", "2rem"],
} as const;

function fontSize(): Record<string, [string, { lineHeight: string }]> {
  return Object.fromEntries(
    Object.entries(FONT_SIZES).map(([name, [size, leading]]) => [
      name,
      [
        `var(--karni-font-size-${name}, ${size})`,
        { lineHeight: `var(--karni-font-leading-${name}, ${leading})` },
      ],
    ]),
  );
}

const karniPreset = {
  // `as const` keeps the literal type so the preset stays assignable to
  // Config["presets"] when consumers spread it into their own config.
  darkMode: "class" as const,
  theme: {
    extend: {
      colors: {
        background: color("background"),
        foreground: color("foreground"),
        card: { DEFAULT: color("card"), foreground: color("card-foreground") },
        popover: { DEFAULT: color("popover"), foreground: color("popover-foreground") },
        primary: {
          DEFAULT: color("primary"),
          foreground: color("primary-foreground"),
          hover: color("primary-hover"),
        },
        secondary: {
          DEFAULT: color("secondary"),
          foreground: color("secondary-foreground"),
          hover: color("secondary-hover"),
        },
        muted: {
          DEFAULT: color("muted"),
          foreground: color("muted-foreground"),
          subtle: color("muted-subtle"),
        },
        accent: { DEFAULT: color("accent"), foreground: color("accent-foreground") },
        destructive: {
          DEFAULT: color("destructive"),
          foreground: color("destructive-foreground"),
          hover: color("destructive-hover"),
          subtle: color("destructive-subtle"),
          border: color("destructive-border"),
        },
        border: color("border"),
        input: color("input"),
        ring: color("ring"),
        overlay: color("overlay"),
        chart: {
          "1": color("chart-1"),
          "2": color("chart-2"),
          "3": color("chart-3"),
          "4": color("chart-4"),
          "5": color("chart-5"),
        },
      },
      borderColor: {
        // A bare `border` class uses the token, never Tailwind's default gray.
        DEFAULT: color("border"),
      },
      spacing: spacing(),
      borderRadius: {
        DEFAULT: "var(--karni-radius-sm, 0.25rem)",
        sm: "var(--karni-radius-sm, 0.25rem)",
        md: "var(--karni-radius-md, 0.375rem)",
        lg: "var(--karni-radius-lg, 0.5rem)",
        xl: "var(--karni-radius-xl, 0.75rem)",
        full: "var(--karni-radius-full, 9999px)",
      },
      fontFamily: {
        sans: "var(--karni-font-sans, ui-sans-serif, system-ui, sans-serif)",
        mono: "var(--karni-font-mono, ui-monospace, monospace)",
      },
      fontSize: fontSize(),
      fontWeight: {
        normal: "var(--karni-font-weight-normal, 400)",
        medium: "var(--karni-font-weight-medium, 500)",
        semibold: "var(--karni-font-weight-semibold, 600)",
        bold: "var(--karni-font-weight-bold, 700)",
      },
      lineHeight: { none: "var(--karni-font-leading-none, 1)" },
      textUnderlineOffset: { "4": "var(--karni-font-underline-offset, 4px)" },
      letterSpacing: {
        tight: "var(--karni-font-tracking-tight, -0.025em)",
        wide: "var(--karni-font-tracking-wide, 0.025em)",
      },
      boxShadow: {
        sm: "var(--karni-shadow-sm, 0 1px 3px 0 rgb(0 0 0 / 0.1))",
        DEFAULT: "var(--karni-shadow, 0 1px 3px 0 rgb(0 0 0 / 0.1))",
        md: "var(--karni-shadow-md, 0 4px 6px -1px rgb(0 0 0 / 0.1))",
        lg: "var(--karni-shadow-lg, 0 10px 15px -3px rgb(0 0 0 / 0.1))",
      },
      borderWidth: {
        DEFAULT: "var(--karni-border-width, 1px)",
        "2": "var(--karni-border-width-2, 2px)",
      },
      divideWidth: { DEFAULT: "var(--karni-border-width, 1px)" },
      outlineWidth: { DEFAULT: "var(--karni-border-width, 1px)" },
      ringWidth: {
        "1": "var(--karni-ring-width-1, 1px)",
        "2": "var(--karni-ring-width, 2px)",
      },
      ringOffsetWidth: { "2": "var(--karni-ring-offset-width, 2px)" },
      zIndex: {
        raised: "var(--karni-z-raised, 10)",
        drawer: "var(--karni-z-drawer, 40)",
        popover: "var(--karni-z-popover, 50)",
        modal: "var(--karni-z-modal, 50)",
        toast: "var(--karni-z-toast, 100)",
      },
      opacity: {
        "50": "var(--karni-opacity-50, 0.5)",
        "60": "var(--karni-opacity-60, 0.6)",
        "70": "var(--karni-opacity-70, 0.7)",
        "90": "var(--karni-opacity-90, 0.9)",
      },
      transitionDuration: { DEFAULT: "var(--karni-duration, 150ms)" },
      transitionTimingFunction: { DEFAULT: "var(--karni-ease, cubic-bezier(0.4, 0, 0.2, 1))" },
      animation: {
        pulse: "pulse var(--karni-duration-pulse, 2s) cubic-bezier(0.4, 0, 0.6, 1) infinite",
        spin: "spin var(--karni-duration-spin, 1s) linear infinite",
      },
    },
  },
} satisfies Omit<Config, "content">;

export default karniPreset;
