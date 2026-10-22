/**
 * Every visual value a component's classes compile to resolves from a
 * --karni-* token. karni/no-style-literals stops literals in the source; this
 * test catches the other half: a class the preset does not map, which
 * Tailwind would fill from its own default theme. It compiles every class in
 * src/ the way a Tailwind 4 project does (tailwindcss + tailwind-v4.css +
 * the preset through @config) and checks the utilities layer.
 */
import tailwind from "@tailwindcss/postcss";
import postcss, { type AtRule, type Declaration, type Rule } from "postcss";
import { describe, expect, it } from "vitest";

/** The package root: vitest runs from it (import.meta.url is a vite /@fs URL here). */
const ROOT = process.cwd();

const ENTRY = `
@import "tailwindcss" source(none);
@import "${ROOT}/src/tailwind-v4.css";
@config "./tokens.tailwind.config.ts";
@source "../src";
@source not "../src/**/*.test.tsx";
@source not "../src/**/*.test.ts";
@source not "../src/**/*.stories.tsx";
@source not "../src/components/brand/mark-paths.ts";
`;

/** Not design values: the screen-reader-only box is the same everywhere. */
const EXEMPT_SELECTORS = new Set([".sr-only", ".not-sr-only"]);

/** Properties that carry design values (layout counts such as flex: 1 do not). */
const VISUAL =
  /^(?:--tw-[\w-]+|color|background(?:-color)?|border(?:-[a-z]+)*|outline(?:-[a-z]+)*|padding(?:-[a-z]+)*|margin(?:-[a-z]+)*|(?:row-|column-)?gap|(?:min-|max-)?(?:width|height)|inset(?:-[a-z]+)*|top|right|bottom|left|font(?:-[a-z]+)*|line-height|letter-spacing|text-underline-offset|text-decoration-thickness|box-shadow|z-index|opacity|transition(?:-[a-z]+)*|animation(?:-[a-z]+)*|fill|stroke(?:-width)?|translate|scale|rotate)$/;

/** Plumbing Tailwind composes values from, and layout geometry Radix measures. */
const PLUMBING = /var\(--(?:tw|radix)-[\w-]+(?:,[^()]*(?:\([^()]*\))?[^()]*)?\)/g;
const FRACTION = /calc\(-?\d+ \/ \d+ \* 100%\)|\* -1\b|\b100v[hw]\b|\b100dvh\b/g;
const LITERAL =
  /(?<![\w-])(?!0(?:px)?(?![\w.%])|100%)-?\d*\.?\d+(?:px|rem|em|ms|s|%|vh|vw|dvh)?(?![\w-])|#[0-9a-f]{3,8}\b|\b(?:rgb|rgba|hsl|hsla|oklch|oklab)\(/i;

async function compile(): Promise<postcss.Root> {
  const result = await postcss([tailwind({ base: ROOT })]).process(ENTRY, {
    from: `${ROOT}/tests/tokens-entry.css`,
  });
  return postcss.parse(result.css);
}

/** The declarations in the utilities layer whose value is a literal, as `selector { prop: value }`. */
function literals(root: postcss.Root): string[] {
  const found = new Set<string>();
  root.walkAtRules("layer", (layer: AtRule) => {
    if (layer.params !== "utilities") return;
    layer.walkRules((rule: Rule) => {
      if (EXEMPT_SELECTORS.has(rule.selector)) return;
      const last = new Map<string, Declaration>();
      rule.each((node) => {
        if (node.type === "decl") last.set(node.prop, node);
      });
      for (const decl of last.values()) {
        if (!VISUAL.test(decl.prop) || decl.value.includes("var(--karni-")) continue;
        const rest = decl.value.replace(PLUMBING, "").replace(FRACTION, "");
        // A literal, or a variable from Tailwind's own theme (--text-3xl, --spacing).
        if (LITERAL.test(rest) || rest.includes("var(--")) {
          found.add(`${rule.selector} { ${decl.prop}: ${decl.value} }`);
        }
      }
    });
  });
  return [...found].sort();
}

describe("design tokens", () => {
  it("every visual value the components compile to reads a --karni-* token", async () => {
    const root = await compile();
    let utilities = 0;
    root.walkAtRules("layer", (layer) => {
      if (layer.params === "utilities") layer.walkRules(() => void (utilities += 1));
    });
    expect(utilities).toBeGreaterThan(200);
    expect(literals(root)).toEqual([]);
  }, 30_000);

  it("transitions read the motion tokens under Tailwind 4", async () => {
    const root = await compile();
    const theme: Record<string, string> = {};
    root.walkDecls(/^--default-transition-/, (decl) => {
      theme[decl.prop] = decl.value;
    });
    expect(theme["--default-transition-duration"]).toBe("var(--karni-duration)");
    expect(theme["--default-transition-timing-function"]).toBe("var(--karni-ease)");
  }, 30_000);
});
