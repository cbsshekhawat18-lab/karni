// @vitest-environment node
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const cache = join(root, "node_modules", ".cache");
mkdirSync(cache, { recursive: true });
const work = mkdtempSync(join(cache, "karni-game-2d-"));

/**
 * The gzip budgets of the entry points, minified as a game's build minifies
 * them (whitespace too). Set from the first build: raising one needs a
 * CHANGELOG note.
 */
const BUDGETS = { draw: 7_100, collide: 2_200 } as const;

/** Bundle `entries` (name to source) minified whole, as a game's production build would. */
async function bundle(outDir: string, entries: Record<string, string>): Promise<void> {
  const { build } = await import("vite");
  await build({
    logLevel: "silent",
    configFile: false,
    build: {
      outDir,
      emptyOutDir: true,
      minify: true,
      // Library mode keeps whitespace in ES output: a game's own build does not.
      rollupOptions: { output: { minify: true } },
      lib: { entry: entries, formats: ["es"], fileName: (_format, name) => `${name}.js` },
    },
  });
}

const read = (dir: string, name: string): string => readFileSync(join(dir, `${name}.js`), "utf8");
const gzip = (code: string): number => gzipSync(code, { level: 9 }).length;

beforeAll(async () => {
  await bundle(join(work, "full"), {
    draw: join(root, "src/draw/index.ts"),
    collide: join(root, "src/collide/index.ts"),
  });
}, 120_000);
afterAll(() => rmSync(work, { recursive: true, force: true }));

describe("the draw and collide bundles", () => {
  it("stay within their gzip budgets", () => {
    for (const name of Object.keys(BUDGETS) as (keyof typeof BUDGETS)[]) {
      const size = gzip(read(join(work, "full"), name));
      expect(size, `${name} is ${size} bytes gzipped`).toBeLessThanOrEqual(BUDGETS[name]);
    }
  });

  it("import nothing: no runtime dependency, not even the package's own main entry", () => {
    for (const name of Object.keys(BUDGETS)) {
      const code = read(join(work, "full"), name);
      expect(code, name).not.toMatch(/\bimport\s*[\w{*"]|\bimport\(|\brequire\(/);
    }
  });

  it("bundle only what a game imports", { timeout: 120_000 }, async () => {
    const entry = join(work, "pool-only.ts");
    writeFileSync(
      entry,
      `import { createPool } from ${JSON.stringify(join(root, "src/draw/index.ts"))};\n` +
        `import { boxesOverlap } from ${JSON.stringify(join(root, "src/collide/index.ts"))};\n` +
        `export const pool = createPool({ create: () => ({ x: 0 }) });\n` +
        `export const hit = boxesOverlap({ x: 0, y: 0, w: 1, h: 1 }, { x: 0, y: 0, w: 1, h: 1 });\n`,
    );
    const out = join(work, "shaken");
    await bundle(out, { entry });
    const code = read(out, "entry");
    expect(code).not.toContain("drawImage");
    expect(code).not.toContain("setTransform");
    expect(code).not.toContain("matchMedia");
    expect(gzip(code)).toBeLessThan(600);
  });

  it(
    "make no garbage per frame: a few boxed numbers at most, whatever the count of things",
    {
      timeout: 120_000,
    },
    () => {
      const script = join(root, "tests/fixtures/per-frame/scenarios.mjs");
      const output = execFileSync(process.execPath, ["--expose-gc", script, join(work, "full")], {
        encoding: "utf8",
        timeout: 110_000,
      });
      const results = JSON.parse(output) as Record<string, number>;
      expect(results.particlesAlive).toBeGreaterThan(100);
      expect(results.triggersEntered).toBeGreaterThan(0);
      // Each scenario has 50 to 300 things on screen: one object made per thing per frame
      // would grow the heap by thousands of bytes a frame. What may stay is the engine
      // boxing a number at a call it did not inline, a few bytes a frame.
      for (const scenario of ["render", "particles", "tweens", "collide"]) {
        expect(results[scenario], `${scenario}: ${results[scenario]} bytes a frame`).toBeLessThan(
          128,
        );
      }
    },
  );
});
