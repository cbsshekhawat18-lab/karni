import { mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "vite";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { runSmoke } from "../src/smoke";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const example = join(root, "example", "crate-climb");
const cache = join(root, "node_modules", ".cache");
mkdirSync(cache, { recursive: true });
const work = mkdtempSync(join(cache, "karni-game-climb-"));
const dist = join(work, "dist");

beforeAll(async () => {
  await build({
    configFile: join(example, "vite.config.ts"),
    build: { outDir: dist, emptyOutDir: true },
    logLevel: "error",
  });
});
afterAll(() => rmSync(work, { recursive: true, force: true }));

const hud = (page: import("playwright").Page) =>
  page.evaluate(() => ({ ...(document.getElementById("hud") as HTMLElement).dataset }));

const ready = async (page: import("playwright").Page): Promise<void> => {
  await page.waitForFunction(() => document.getElementById("hud")?.dataset.ready === "1");
};

describe("Crate Climb in a headless browser", () => {
  it("starts, runs right taking gems, and the camera follows, with no console error", async () => {
    let seen: Record<string, string | undefined> = {};
    const result = await runSmoke({
      dir: dist,
      seconds: 3,
      corruptStorage: false,
      script: [
        { at: 200, key: "Space" },
        { at: 400, key: "ArrowRight", action: "down" },
        { at: 2600, key: "ArrowRight", action: "up" },
      ],
      ready,
      check: async (page) => {
        seen = await hud(page);
      },
    });
    expect(result.problems).toEqual([]);
    expect(seen.screen).toBe("play");
    expect(Number(seen.gems)).toBeGreaterThanOrEqual(2);
    // The climber ran past the dead zone: the camera moved right after it.
    expect(Number(seen.cameraX)).toBeGreaterThan(300);
    expect(Number(seen.playerX)).toBeGreaterThan(300);
  });

  it("starts with a tap on a phone", async () => {
    const result = await runSmoke({
      dir: dist,
      seconds: 1.5,
      touch: true,
      viewport: { width: 390, height: 844 },
      corruptStorage: false,
      script: [{ at: 300, tap: { x: 0.8, y: 0.5 } }],
      ready,
      check: async (page) => {
        expect((await hud(page)).screen).toBe("play");
      },
    });
    expect(result.problems).toEqual([]);
  });
});
