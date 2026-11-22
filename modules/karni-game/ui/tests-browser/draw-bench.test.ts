import { mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, type Browser } from "playwright";
import { build } from "vite";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { serveFolder } from "../src/smoke";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const fixture = join(root, "tests", "fixtures", "draw-bench");
const cache = join(root, "node_modules", ".cache");
mkdirSync(cache, { recursive: true });
const work = mkdtempSync(join(cache, "karni-game-bench-"));

/**
 * The frame budget: the 95th percentile of one frame's work (update and
 * draw) for the load below. A 60 Hz frame is 16.7 ms and the browser needs
 * part of it, so the layer's own work must stay well under. The budget is
 * set with room for a shared CI runner, about four times what a laptop
 * measures. KARNI_GAME_BENCH_BUDGET_MS changes it for a slower machine.
 */
const BUDGET_MS = Number(process.env.KARNI_GAME_BENCH_BUDGET_MS ?? 12);
const LOAD = { sprites: 2000, particles: 1500, frames: 300 };

interface Bench {
  sprites: number;
  particles: number;
  frames: number;
  workMean: number;
  workP50: number;
  workP95: number;
  workMax: number;
  intervalMean: number;
  intervalP95: number;
  drawn: number;
  culled: number;
}

let browser: Browser;
let server: { url: string; close(): Promise<void> };

beforeAll(async () => {
  await build({
    configFile: join(fixture, "vite.config.ts"),
    build: { outDir: join(work, "dist"), emptyOutDir: true },
    logLevel: "error",
  });
  server = await serveFolder(join(work, "dist"));
  browser = await chromium.launch();
});
afterAll(async () => {
  await browser?.close();
  await server?.close();
  rmSync(work, { recursive: true, force: true });
});

async function bench(viewport: { width: number; height: number }): Promise<Bench> {
  const page = await browser.newPage({ viewport });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  const query = new URLSearchParams(
    Object.entries(LOAD).map(([key, value]) => [key, String(value)]),
  );
  await page.goto(`${server.url}?${query}`);
  await page.waitForFunction(() => document.title === "done", undefined, { timeout: 90_000 });
  const result = (await page.evaluate(
    () => (window as unknown as { __bench: unknown }).__bench,
  )) as Bench;
  await page.close();
  expect(errors).toEqual([]);
  return result;
}

describe("the 2D layer under load in a headless browser", () => {
  for (const [name, viewport] of [
    ["desktop", { width: 1280, height: 720 }],
    ["phone", { width: 390, height: 844 }],
  ] as const) {
    it(`draws ${LOAD.sprites} sprites and ${LOAD.particles} particles within the frame budget (${name})`, async () => {
      const result = await bench(viewport);
      console.log(`[draw-bench ${name}]`, JSON.stringify(result));
      expect(result.frames).toBe(LOAD.frames);
      expect(result.particles).toBeGreaterThan(LOAD.particles * 0.8);
      // The camera shows a third of the world: most sprites are culled, not drawn.
      expect(result.culled).toBeGreaterThan(LOAD.sprites / 2);
      expect(result.workP95).toBeLessThan(BUDGET_MS);
      // The time between frames is reported, not asserted: it depends on the machine's raster speed.
    });
  }
});
