// @vitest-environment node
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";
import { describe, expect, it } from "vitest";

const ui = resolve(dirname(fileURLToPath(import.meta.url)), "..");

/**
 * The gzip budgets of the `scenes` and `ui` entry points, in bytes, for the
 * whole entry minified with its shared chunks. Set from the first build
 * (2414 and 9349 bytes). Raise one only with a CHANGELOG note.
 */
const SCENES_BUDGET = 2600;
const UI_BUDGET = 9800;
/** A game that opens a dialog and nothing else (4979 bytes at the first build). */
const DIALOG_BUDGET = 5300;

async function bundle(source: string): Promise<{ code: string; gzip: number }> {
  const { build } = await import("vite");
  const cache = join(ui, "node_modules/.cache");
  mkdirSync(cache, { recursive: true });
  const dir = mkdtempSync(join(cache, "karni-game-size-"));
  try {
    const entry = join(dir, "entry.ts");
    writeFileSync(
      entry,
      source
        .replaceAll("SCENES", JSON.stringify(join(ui, "src/scenes/index.ts")))
        .replaceAll("UI", JSON.stringify(join(ui, "src/ui/index.ts"))),
    );
    const output = await build({
      logLevel: "silent",
      configFile: false,
      build: { write: false, minify: true, lib: { entry, formats: ["es"], fileName: "entry" } },
    });
    const results = Array.isArray(output) ? output : [output];
    const code = results
      .flatMap((result) => ("output" in result ? result.output : []))
      .map((chunk) => ("code" in chunk ? chunk.code : ""))
      .join("\n");
    return { code, gzip: gzipSync(code).length };
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

describe("the scenes entry point", () => {
  it("stays inside its gzip size budget, with every export in", { timeout: 60_000 }, async () => {
    const { gzip } = await bundle(`export * from SCENES;`);
    expect(gzip).toBeLessThan(SCENES_BUDGET);
  });

  it(
    "is tree-shaken and browser-safe: the entity list alone bundles no stack and no store",
    { timeout: 60_000 },
    async () => {
      const { code, gzip } = await bundle(
        `import { createEntityList } from SCENES;\nexport const list = createEntityList<object>();\n`,
      );
      expect(gzip).toBeLessThan(900);
      expect(code).not.toContain("prefers-reduced-motion");
      expect(code).not.toContain("pagehide");
      const all = await bundle(`export * from SCENES;`);
      expect(all.code).not.toMatch(/node:|require\(/);
    },
  );
});

describe("the ui entry point", () => {
  it("stays inside its gzip size budget, with every export in", { timeout: 60_000 }, async () => {
    const { gzip } = await bundle(`export * from UI;`);
    expect(gzip).toBeLessThan(UI_BUDGET);
  });

  it(
    "is tree-shaken: a game that only opens a dialog bundles no settings, no touch buttons and no dev overlay",
    { timeout: 60_000 },
    async () => {
      const { code, gzip } = await bundle(
        `import { createUi } from UI;\nexport const open = () => createUi().dialog({ title: "Hi" });\n`,
      );
      expect(gzip).toBeLessThan(DIALOG_BUDGET);
      expect(code).not.toContain("data-kg-touch");
      expect(code).not.toContain("setPointerCapture");
      expect(code).not.toContain("aria-valuetext");
      expect(code).not.toContain("requestAnimationFrame");
      expect(code).not.toContain("__KARNI_GAME_DEV__");
    },
  );

  it(
    "has no runtime dependency and touches no storage or network by itself",
    { timeout: 60_000 },
    async () => {
      const { code } = await bundle(`export * from UI;`);
      expect(code).not.toMatch(/node:|require\(/);
      expect(code).not.toContain("fetch(");
      expect(code).not.toContain("XMLHttpRequest");
    },
  );
});
