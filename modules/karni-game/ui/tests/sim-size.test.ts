// @vitest-environment node
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";
import { describe, expect, it } from "vitest";

const ui = resolve(dirname(fileURLToPath(import.meta.url)), "..");

/**
 * The gzip budget of the `sim` entry point, in bytes, for the whole entry
 * minified with its shared chunks. Set from the first build (6586 and 1910 bytes). Raise it only
 * with a CHANGELOG note.
 */
const SIM_BUDGET = 7200;
/** What a game that imports only the hash and the sim bundles. */
const CORE_BUDGET = 2300;

async function bundle(source: string): Promise<{ code: string; gzip: number }> {
  const { build } = await import("vite");
  const cache = join(ui, "node_modules/.cache");
  mkdirSync(cache, { recursive: true });
  const dir = mkdtempSync(join(cache, "karni-game-size-"));
  try {
    const entry = join(dir, "entry.ts");
    writeFileSync(entry, source.replaceAll("SIM", JSON.stringify(join(ui, "src/sim/index.ts"))));
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

describe("the sim entry point", () => {
  it("stays inside its gzip size budget, with every export in", { timeout: 60_000 }, async () => {
    const { gzip } = await bundle(`export * from SIM;`);
    expect(gzip).toBeLessThan(SIM_BUDGET);
  });

  it(
    "is tree-shaken: a game that imports the sim and the hash bundles no test kit, no loop",
    { timeout: 60_000 },
    async () => {
      const { code, gzip } = await bundle(
        `import { createSim, defineSim, hashState } from SIM;\n` +
          `const rules = defineSim({ idle: 0, init: () => ({ n: 0 }), step: (s: { n: number }) => { s.n += 1; } });\n` +
          `export const hash = hashState(createSim(rules, { seed: 1 }).state);\n`,
      );
      expect(gzip).toBeLessThan(CORE_BUDGET);
      expect(code).not.toContain("not deterministic");
      expect(code).not.toContain("requestAnimationFrame");
      expect(code).not.toContain("karni-allow");
    },
  );

  it(
    "is browser-safe: it imports no Node module and touches no page or storage",
    { timeout: 60_000 },
    async () => {
      const { code } = await bundle(`export * from SIM;`);
      expect(code).not.toMatch(/node:|require\(/);
      expect(code).not.toContain("X-Player-Token");
    },
  );
});
