import { mkdirSync, mkdtempSync, readdirSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "vite";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { runSmoke, type SmokeStep } from "../src/smoke";
import { checkPackage, portalRow } from "../src/tooling";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const example = join(root, "example", "block-hopper");
const cache = join(root, "node_modules", ".cache");
mkdirSync(cache, { recursive: true });
const work = mkdtempSync(join(cache, "karni-game-smoke-"));
const web = join(work, "web");
const single = join(work, "single");

beforeAll(async () => {
  await build({
    configFile: join(example, "vite.config.ts"),
    build: { outDir: web, emptyOutDir: true },
    logLevel: "error",
  });
  process.env.BLOCK_HOPPER_SINGLE = "1";
  await build({
    configFile: join(example, "vite.config.ts"),
    build: { outDir: single, emptyOutDir: true },
    logLevel: "error",
  });
  delete process.env.BLOCK_HOPPER_SINGLE;
});
afterAll(() => rmSync(work, { recursive: true, force: true }));

const hud = (page: import("playwright").Page) =>
  page.evaluate(() => ({ ...(document.getElementById("hud") as HTMLElement).dataset }));

/** Start, walk left off the first platform, fall: a whole run in about two seconds. */
const fallingRun: SmokeStep[] = [
  { at: 200, key: "Space" },
  { at: 400, key: "ArrowLeft", action: "down" },
  { at: 2200, key: "ArrowLeft", action: "up" },
];

describe("Block Hopper in a headless browser", () => {
  it("is a clean web package", () => {
    expect(checkPackage(web, portalRow("web"))).toEqual([]);
    expect(readdirSync(single)).toEqual(["index.html"]);
  });

  it("boots, plays a run with scripted keys, saves it and puts it on the board, with no console error", async () => {
    const seen: Record<string, Record<string, string | undefined>> = {};
    const result = await runSmoke({
      dir: web,
      seconds: 4,
      script: fallingRun,
      ready: async (page) => {
        await page.waitForFunction(
          () => document.getElementById("hud")?.dataset.screen === "title",
        );
      },
      check: async (page, phase) => {
        seen[phase] = await hud(page);
        if (phase === "play") {
          const stored = await page.evaluate(() => ({
            save: window.localStorage.getItem("block-hopper.save"),
            board: window.localStorage.getItem("block-hopper.local.board.high"),
          }));
          seen.stored = { save: stored.save ?? undefined, board: stored.board ?? undefined };
        }
      },
    });
    expect(result.problems).toEqual([]);
    expect(result.ok).toBe(true);
    expect(seen.play?.screen).toBe("over");
    expect(JSON.parse(seen.stored?.save ?? "{}")).toMatchObject({ v: 2, data: { plays: 1 } });
    expect(JSON.parse(seen.stored?.board ?? "[]")).toHaveLength(1);
    expect(result.storageKeys).toEqual(
      expect.arrayContaining(["block-hopper.save", "block-hopper.player"]),
    );
    // The second boot found every value broken, kept the bad save aside and played on.
    expect(seen.corrupt?.loaded).toBe("corrupt");
    expect(seen.corrupt?.screen).toBe("over");
  });

  it("plays by touch with a tap to start", async () => {
    const result = await runSmoke({
      dir: web,
      seconds: 2,
      touch: true,
      viewport: { width: 390, height: 844 },
      corruptStorage: false,
      script: [{ at: 200, tap: { x: 0.8, y: 0.5 } }],
      ready: async (page) => {
        await page.waitForFunction(
          () => document.getElementById("hud")?.dataset.screen === "title",
        );
      },
      check: async (page) => {
        expect((await hud(page)).screen).toBe("play");
      },
    });
    expect(result.problems).toEqual([]);
  });

  it("runs the single-file build from file://", async () => {
    const result = await runSmoke({
      url: pathToFileURL(join(single, "index.html")).href,
      seconds: 3,
      script: fallingRun,
      corruptStorage: false,
      ready: async (page) => {
        await page.waitForFunction(
          () => document.getElementById("hud")?.dataset.screen === "title",
        );
      },
      check: async (page) => {
        expect((await hud(page)).screen).toBe("over");
      },
    });
    expect(result.problems).toEqual([]);
  });

  it("reports a console error and a canvas that never changes", async () => {
    const result = await runSmoke({
      url: "data:text/html,<canvas></canvas><script>console.error('broken boot')</script>",
      seconds: 0.5,
      corruptStorage: false,
    });
    expect(result.ok).toBe(false);
    expect(result.problems).toEqual([
      "play: console error: broken boot",
      "play: the canvas did not change while playing",
    ]);
  });
});
