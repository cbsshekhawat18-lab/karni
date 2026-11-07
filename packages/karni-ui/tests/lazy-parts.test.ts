/**
 * The heavy parts of the page blocks load on first use, so a page that does
 * not use them pays nothing: the markdown parser and sanitizer (marked,
 * DOMPurify) through MarkdownView's renderer, and the XLSX writer through
 * DataTable's export. This scans the shipped source: those modules are
 * reached only through `import()` (or a type-only import), and nothing else
 * imports the two libraries.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(process.cwd(), "src");

function sources(dir: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) found.push(...sources(path));
    else if (/\.tsx?$/.test(entry) && !/\.(test|stories)\.tsx?$/.test(entry)) found.push(path);
  }
  return found;
}

/** Every static `import ... from "x"` (type-only ones left out) in `text`. */
function staticImports(text: string): string[] {
  const found: string[] = [];
  for (const match of text.matchAll(/^import\s+(type\s+)?[^;]*?from\s+"([^"]+)";/gms)) {
    if (match[1] === undefined && match[2] !== undefined) found.push(match[2]);
  }
  return found;
}

/** Each lazy module, and how an import of it is spelled. */
const LAZY: Record<string, RegExp> = {
  "components/markdown/render.ts": /\/render$/,
  "components/data-table/xlsx.ts": /\/xlsx$/,
};

describe("heavy parts load lazily", () => {
  const files = sources(SRC).map((path) => ({
    path: relative(SRC, path),
    text: readFileSync(path, "utf8"),
  }));

  it("only the lazy modules import marked and DOMPurify", () => {
    const importers = files
      .filter((file) =>
        staticImports(file.text).some((name) => name === "marked" || name === "dompurify"),
      )
      .map((file) => file.path);
    expect(importers).toEqual(["components/markdown/render.ts"]);
  });

  it("no module imports a lazy module statically, and each has an import() caller", () => {
    for (const [lazy, module] of Object.entries(LAZY)) {
      const statically = files.filter((file) =>
        staticImports(file.text).some((name) => module.test(name) && name.startsWith(".")),
      );
      expect(
        statically.map((file) => file.path),
        lazy,
      ).toEqual([]);
      const dynamic = files.filter((file) =>
        new RegExp(`import\\("\\./${lazy.split("/").pop()?.replace(".ts", "")}"\\)`).test(
          file.text,
        ),
      );
      expect(dynamic.length, lazy).toBeGreaterThan(0);
    }
  });
});
