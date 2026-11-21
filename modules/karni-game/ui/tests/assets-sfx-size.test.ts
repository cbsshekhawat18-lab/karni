// @vitest-environment node
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";
import { describe, expect, it } from "vitest";

const ui = resolve(dirname(fileURLToPath(import.meta.url)), "..");

/**
 * The gzip budgets of the `assets` and `sfx` entry points, in bytes, for the
 * whole entry minified with its shared chunks. Measured at 2974 (assets) and
 * 2666 (sfx) bytes, with about 15% room. Raise one only with a CHANGELOG note.
 */
const ASSETS_BUDGET = 3400;
const SFX_BUDGET = 3100;
/** A game that renders a tone and nothing else (no loader, no music). */
const SYNTH_BUDGET = 1300;
/** A game that loads one group and nothing else. */
const LOAD_BUDGET = 3400;

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
        .replaceAll("ASSETS", JSON.stringify(join(ui, "src/assets/index.ts")))
        .replaceAll("SFX", JSON.stringify(join(ui, "src/sfx/index.ts"))),
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
    const gzip = gzipSync(code).length;
    return { code, gzip };
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

describe("the assets entry point", () => {
  it("stays inside its gzip size budget, with every export in", { timeout: 60_000 }, async () => {
    const { gzip } = await bundle(`export * from ASSETS;`);
    expect(gzip).toBeLessThan(ASSETS_BUDGET);
  });

  it(
    "is tree-shaken: a game that only declares its manifest bundles no loader",
    { timeout: 60_000 },
    async () => {
      const { code } = await bundle(
        `import { defineManifest } from ASSETS;\nexport const m = defineManifest({ groups: {} });\n`,
      );
      expect(code).not.toContain("createImageBitmap");
      expect(code).not.toContain("FontFace");
    },
  );

  it(
    "loads a group in little code, and has no dependency, no node import and no hidden network",
    { timeout: 60_000 },
    async () => {
      const { code, gzip } = await bundle(
        `import { createAssets } from ASSETS;\nexport const a = createAssets({ manifest: { groups: {} } });\n`,
      );
      expect(gzip).toBeLessThan(LOAD_BUDGET);
      const all = await bundle(`export * from ASSETS;`);
      expect(all.code).not.toMatch(/node:|require\(/);
      // The only fetch is the loader's own, through the replaceable platform.
      expect(code.match(/(?<![.\w])fetch\(/g)?.length ?? 0).toBeLessThanOrEqual(1);
      expect(all.code).not.toContain("XMLHttpRequest");
    },
  );
});

describe("the sfx entry point", () => {
  it("stays inside its gzip size budget, with every export in", { timeout: 60_000 }, async () => {
    const { gzip } = await bundle(`export * from SFX;`);
    expect(gzip).toBeLessThan(SFX_BUDGET);
  });

  it(
    "is tree-shaken: rendering a tone alone bundles no player, no ducking and no presets",
    { timeout: 60_000 },
    async () => {
      const { code, gzip } = await bundle(
        `import { renderSpec, tone } from SFX;\nexport const s = renderSpec(tone(440, 0.1), 8000);\n`,
      );
      expect(gzip).toBeLessThan(SYNTH_BUDGET);
      expect(code).not.toContain("linearRampToValueAtTime");
      expect(code).not.toContain("onUnlock");
      expect(code).not.toContain("lowpass: 3e3");
    },
  );

  it(
    "has no dependency, no node import, no network and no storage",
    { timeout: 60_000 },
    async () => {
      const { code } = await bundle(`export * from SFX;`);
      expect(code).not.toMatch(/node:|require\(/);
      expect(code).not.toContain("fetch(");
      expect(code).not.toContain("localStorage");
    },
  );
});
