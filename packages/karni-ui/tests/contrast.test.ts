/**
 * The colour pairs the components put together meet WCAG 2.2 AA in both
 * themes: 4.5:1 for text, 3:1 for the parts of a control a user must see
 * (a field's boundary, a switch's track, a focus ring, an icon-only button)
 * and for chart series. Computed from the token values in src/styles.css, so
 * a token change that breaks a pair fails here with the ratio it fell to.
 *
 * Translucent shades (`muted-subtle`, `destructive-subtle`, text at
 * `opacity-90`) are composited over the surface they sit on, as the browser
 * paints them.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

type Rgb = readonly [number, number, number];

const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");

/** The `--karni-<name>: H S% L%` triplets declared in the first block for `selector`. */
function triplets(selector: string): Record<string, string> {
  const start = css.indexOf(`${selector} {`);
  if (start === -1) throw new Error(`styles.css has no "${selector} {" block`);
  const body = css.slice(start, css.indexOf("}", start));
  const found: Record<string, string> = {};
  for (const match of body.matchAll(/--karni-([\w-]+):\s*([\d.]+ [\d.]+% [\d.]+%);/g)) {
    const [, name, value] = match;
    if (name !== undefined && value !== undefined) found[name] = value;
  }
  return found;
}

function hslToRgb(triplet: string): Rgb {
  const [h, s, l] = triplet.split(" ").map((part) => Number.parseFloat(part));
  if (h === undefined || s === undefined || l === undefined) throw new Error(triplet);
  const sat = s / 100;
  const light = l / 100;
  const k = (n: number): number => (n + h / 30) % 12;
  const a = sat * Math.min(light, 1 - light);
  const f = (n: number): number =>
    light - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return [f(0), f(8), f(4)];
}

function luminance([r, g, b]: Rgb): number {
  const channel = (c: number): number => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

function contrast(a: Rgb, b: Rgb): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

/** `color` at `alpha` painted over `under` (what color-mix with transparent and opacity-* do). */
function over(color: Rgb, alpha: number, under: Rgb): Rgb {
  return [0, 1, 2].map((i) => alpha * color[i] + (1 - alpha) * under[i]) as unknown as Rgb;
}

const THEMES = {
  light: triplets(":root"),
  dark: { ...triplets(":root"), ...triplets(".dark") },
};

/** A colour by token name; `name@0.9/surface` is the token at 90% opacity over `surface`. */
function resolveColor(theme: Record<string, string>, name: string): Rgb {
  const at = /^([\w-]+)@([\d.]+)\/([\w-]+)$/.exec(name);
  if (at) {
    const [, color, alpha, surface] = at;
    return over(
      resolveColor(theme, color ?? ""),
      Number(alpha),
      resolveColor(theme, surface ?? ""),
    );
  }
  // The derived shades styles.css builds with color-mix(..., transparent).
  const derived: Record<string, [string, number]> = {
    "muted-subtle": ["muted", 0.5],
    "destructive-subtle": ["destructive", 0.1],
    "destructive-hover": ["destructive", 0.9],
    "primary-hover": ["primary", 0.9],
  };
  const mix = derived[name];
  if (mix) return over(resolveColor(theme, mix[0]), mix[1], resolveColor(theme, "background"));
  const triplet = theme[name];
  if (triplet === undefined) throw new Error(`no --karni-${name} token`);
  return hslToRgb(triplet);
}

/** [foreground, surface, where the components use the pair]. */
const TEXT: ReadonlyArray<readonly [string, string, string]> = [
  ["foreground", "background", "body text"],
  ["muted-foreground", "background", "descriptions, nav links, chart axes, placeholders"],
  ["muted-foreground", "card", "Stat label, sidebar nav links"],
  ["muted-foreground", "muted", "inactive Tabs triggers"],
  ["muted-foreground", "muted-subtle", "FileUpload file size"],
  ["muted-foreground", "destructive-subtle", "ErrorState description"],
  ["card-foreground", "card", "Stat value"],
  ["popover-foreground", "popover", "menus, select lists, chart tooltip"],
  ["accent-foreground", "accent", "active nav link, focused menu item"],
  ["primary-foreground", "primary", "Button"],
  ["primary-foreground", "primary-hover", "Button, hovered"],
  ["primary", "muted-subtle", "FileUpload file link"],
  ["secondary-foreground", "secondary", "secondary Button"],
  ["destructive-foreground", "destructive", "destructive Button, error toast"],
  ["destructive-foreground", "destructive-hover", "destructive Button, hovered"],
  ["destructive-foreground@0.9/destructive", "destructive", "error toast description"],
  ["destructive", "background", "field errors, negative Stat delta"],
  ["destructive", "card", "negative Stat delta on a card"],
  ["destructive", "destructive-subtle", "error banners"],
  ["foreground@0.9/background", "background", "toast description"],
  ["foreground@0.9/muted", "muted", "info toast description"],
];

const NON_TEXT: ReadonlyArray<readonly [string, string, string]> = [
  ["input", "background", "the boundary of Input, Textarea, SelectTrigger, FileUpload"],
  ["input", "card", "a field on a card"],
  ["background", "input", "Switch thumb on its unchecked track"],
  ["primary", "background", "Checkbox border, Switch checked track"],
  ["destructive", "background", "an invalid field's border"],
  ["ring", "background", "focus ring"],
  ["ring", "card", "focus ring on a card or the sidebar"],
  ["ring", "muted", "focus ring inside a TabsList"],
  // A toast's close button rings in its text colour (ring-current), so the
  // ring follows the variant: destructive-foreground on an error toast.
  ["destructive-foreground", "destructive", "focus ring of an error toast's close button"],
  ["muted-foreground", "background", "icon-only close buttons"],
  ["chart-1", "background", "chart series 1"],
  ["chart-2", "background", "chart series 2"],
  ["chart-3", "background", "chart series 3"],
  ["chart-4", "background", "chart series 4"],
  ["chart-5", "background", "chart series 5"],
];

function failures(
  pairs: ReadonlyArray<readonly [string, string, string]>,
  minimum: number,
): string[] {
  const failed: string[] = [];
  for (const [themeName, theme] of Object.entries(THEMES)) {
    for (const [fg, bg, use] of pairs) {
      const ratio = contrast(resolveColor(theme, fg), resolveColor(theme, bg));
      if (ratio < minimum) {
        failed.push(`${themeName}: ${fg} on ${bg} is ${ratio.toFixed(2)}:1 (${use})`);
      }
    }
  }
  return failed;
}

describe("token contrast (WCAG 2.2 AA)", () => {
  it("parses both themes from styles.css", () => {
    expect(Object.keys(THEMES.light).length).toBeGreaterThan(20);
    expect(THEMES.dark.background).not.toBe(THEMES.light.background);
  });

  it("computes ratios the way WCAG does", () => {
    expect(contrast([0, 0, 0], [1, 1, 1])).toBeCloseTo(21, 5);
    // Tailwind's gray-500 on white, a well-known 4.83:1.
    expect(contrast(hslToRgb("220 8.9% 46.1%"), [1, 1, 1])).toBeCloseTo(4.83, 2);
  });

  it("text pairs reach 4.5:1 in light and dark", () => {
    expect(failures(TEXT, 4.5)).toEqual([]);
  });

  it("control boundaries, focus rings, icons and chart series reach 3:1", () => {
    expect(failures(NON_TEXT, 3)).toEqual([]);
  });
});
