/**
 * Contract D10 enforcement: no color literals in shipped component source.
 *
 * Every color must resolve through the --karni-* tokens (bg-primary,
 * text-muted-foreground, border-input, …) so that overriding the tokens
 * rethemes the whole library. This test scans the shipped sources under
 * src/components/ and src/lib/ (stories and tests excluded) and fails on:
 * - Tailwind palette classes (bg-red-500, text-gray-700, …)
 * - white/black color utilities (bg-white, text-black, …)
 * - hex colors and raw CSS color functions (#fff, rgb(…), hsl(…), oklch(…))
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// vitest runs with the package root as cwd (import.meta.url is not a file:
// URL under the jsdom environment, so resolve from cwd instead).
const SRC_ROOT = join(process.cwd(), "src");
const SCAN_DIRS = ["components", "lib"] as const;

const PALETTE =
  "slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose";
const COLOR_UTILITIES =
  "bg|text|border|ring-offset|ring|fill|stroke|from|via|to|outline|decoration|divide|accent|caret|shadow|placeholder";

interface BannedPattern {
  name: string;
  re: RegExp;
}

const BANNED: readonly BannedPattern[] = [
  {
    name: "Tailwind palette class",
    re: new RegExp(
      `(?:^|[\\s"'\`:\\[])(?:${COLOR_UTILITIES})-(?:${PALETTE})-\\d{2,3}(?:/\\d{1,3})?\\b`,
    ),
  },
  {
    name: "white/black color utility",
    re: new RegExp(`(?:^|[\\s"'\`:\\[])(?:${COLOR_UTILITIES})-(?:white|black)\\b`),
  },
  { name: "hex color literal", re: /#[0-9a-fA-F]{3,8}\b/ },
  { name: "raw CSS color function", re: /\b(?:rgba?|hsla?|oklch|oklab|lab|lch|color)\(/ },
];

function isShippedSource(path: string): boolean {
  return (
    (path.endsWith(".ts") || path.endsWith(".tsx")) &&
    !path.includes(".test.") &&
    !path.includes(".stories.") &&
    !path.endsWith(".d.ts")
  );
}

function shippedSources(): string[] {
  const files: string[] = [];
  for (const dir of SCAN_DIRS) {
    const base = join(SRC_ROOT, dir);
    for (const entry of readdirSync(base, { recursive: true })) {
      const path = join(base, String(entry));
      if (statSync(path).isFile() && isShippedSource(path)) {
        files.push(path);
      }
    }
  }
  return files;
}

describe("D10: no color literals in component source", () => {
  const files = shippedSources();

  it("finds the component sources", () => {
    expect(files.length).toBeGreaterThan(10);
  });

  it("uses only --karni-* token classes for color", () => {
    const violations: string[] = [];
    for (const file of files) {
      const lines = readFileSync(file, "utf8").split("\n");
      lines.forEach((line, index) => {
        for (const { name, re } of BANNED) {
          if (re.test(line)) {
            violations.push(`${file.slice(SRC_ROOT.length)}:${index + 1} [${name}] ${line.trim()}`);
          }
        }
      });
    }
    expect(violations).toEqual([]);
  });
});
