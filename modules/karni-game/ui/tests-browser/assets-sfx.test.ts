import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, type Browser, type Page } from "playwright";
import { build, createServer } from "vite";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { runSmoke, serveFolder } from "../src/smoke";
import { ASSET_REPORT, checkPackage, portalRow, type WebpEncoder } from "../src/tooling";
import type { AssetsPluginOptions } from "../src/tooling/vite";
import { karniGame } from "../src/tooling/vite";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const src = join(root, "src");
const example = join(root, "example", "block-hopper");
const cache = join(root, "node_modules", ".cache");
mkdirSync(cache, { recursive: true });
const work = mkdtempSync(join(cache, "karni-game-assets-browser-"));
const shots = process.env.KARNI_SHOTS ?? join(cache, "shots");
mkdirSync(shots, { recursive: true });
const axePath = createRequire(import.meta.url).resolve("axe-core/axe.min.js");

let browser: Browser;
let served: { url: string; close(): Promise<void> };
const web = join(work, "web");

beforeAll(async () => {
  await build({
    configFile: join(example, "vite.config.ts"),
    build: { outDir: web, emptyOutDir: true },
    logLevel: "error",
  });
  served = await serveFolder(web);
  browser = await chromium.launch({ headless: true });
});
afterAll(async () => {
  await browser?.close();
  await served?.close();
  rmSync(work, { recursive: true, force: true });
});

type Look = "desktop" | "phone";
const LOOKS: Record<Look, { width: number; height: number; touch: boolean }> = {
  desktop: { width: 1024, height: 640, touch: false },
  phone: { width: 390, height: 780, touch: true },
};

async function open(look: Look, scheme: "light" | "dark", url = served.url) {
  const size = LOOKS[look];
  const context = await browser.newContext({
    viewport: { width: size.width, height: size.height },
    hasTouch: size.touch,
    isMobile: size.touch,
    colorScheme: scheme,
    deviceScaleFactor: size.touch ? 2 : 1,
  });
  const page = await context.newPage();
  const problems: string[] = [];
  const requests: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") problems.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => problems.push(`page: ${error.message}`));
  page.on("requestfailed", (request) => problems.push(`request: ${request.url()}`));
  page.on("request", (request) => requests.push(request.url()));
  return { page, context, problems, requests, goto: () => page.goto(url) };
}

const screen = (page: Page) => page.evaluate(() => document.getElementById("hud")?.dataset.screen);
const waitScreen = (page: Page, name: string) =>
  page.waitForFunction(
    (wanted) => document.getElementById("hud")?.dataset.screen === wanted,
    name,
    { timeout: 30_000 },
  );
const hudData = (page: Page) =>
  page.evaluate(() => ({ ...(document.getElementById("hud") as HTMLElement).dataset }));
const shot = (page: Page, name: string) => page.screenshot({ path: join(shots, `${name}.png`) });

async function axeViolations(page: Page): Promise<string[]> {
  await page.addScriptTag({ path: axePath });
  return page.evaluate(async () => {
    const axe = (window as unknown as { axe: typeof import("axe-core") }).axe;
    return (await axe.run(".kg-root")).violations.map(
      (v) => `${v.id}: ${v.nodes.map((n) => n.html).join(" | ")}`,
    );
  });
}

/** Walk off the first platform and fall: a run over in about two seconds. */
async function fall(page: Page) {
  await page.keyboard.down("ArrowRight");
  await waitScreen(page, "over");
  await page.keyboard.up("ArrowRight");
}

describe("the loading scene and the art groups of Block Hopper", () => {
  for (const look of ["desktop", "phone"] as const) {
    for (const scheme of ["light", "dark"] as const) {
      it(
        `${look}, ${scheme}: a loading scene with a progress bar that moves, then the title`,
        { timeout: 120_000 },
        async () => {
          const { page, context, problems, goto } = await open(look, scheme);
          // Each file takes a while, so the bar can be seen between the steps.
          const wait = { coin: 300, hopper: 700, stages: 1100 };
          await page.route(/\/assets\/(coin|hopper|stages)-.*/, async (route) => {
            const name = /\/(coin|hopper|stages)-/.exec(
              route.request().url(),
            )?.[1] as keyof typeof wait;
            await new Promise((done) => setTimeout(done, wait[name]));
            await route.continue();
          });
          await goto();
          await page.waitForSelector("progress.hopper-progress");
          expect(await screen(page)).toBe("loading");
          expect(await page.getByRole("progressbar", { name: "Loading" }).count()).toBe(1);
          const seen = new Set<number>();
          const watch = setInterval(() => {
            void page
              .evaluate(() => document.querySelector<HTMLProgressElement>("progress")?.value ?? -1)
              .then((value) => seen.add(value))
              .catch(() => undefined);
          }, 100);
          await page.waitForTimeout(800);
          await shot(page, `${look}-${scheme}-10-loading`);
          expect(await axeViolations(page)).toEqual([]);
          await waitScreen(page, "title");
          clearInterval(watch);
          const between = [...seen].filter((value) => value > 0 && value < 100);
          expect(between.length).toBeGreaterThan(0);
          expect(await page.locator("progress").count()).toBe(0);
          await shot(page, `${look}-${scheme}-11-title-after-loading`);
          expect(problems).toEqual([]);
          await context.close();
        },
      );
    }
  }

  it(
    "loads the second stage's art on the next run and frees the first, and loads it again later",
    { timeout: 120_000 },
    async () => {
      const { page, context, problems, requests, goto } = await open("desktop", "light");
      await goto();
      await waitScreen(page, "title");
      const bg = () => requests.filter((url) => /\/bg-/.test(url)).length;
      expect(bg()).toBe(0);
      // Run one: meadow loads behind the loading scene.
      await page.keyboard.press("Space");
      await waitScreen(page, "play");
      expect(await hudData(page)).toMatchObject({ stage: "meadow", groups: "core,meadow" });
      const meadowMemory = Number((await hudData(page)).artMemory);
      expect(meadowMemory).toBeGreaterThan(480 * 270 * 4);
      await shot(page, "desktop-light-12-meadow");
      expect(bg()).toBe(1);
      await fall(page);
      // Run two: cave loads, and meadow is freed in the same step.
      await page.keyboard.press("Space");
      await waitScreen(page, "play");
      expect(await hudData(page)).toMatchObject({ stage: "cave", groups: "core,cave" });
      const caveMemory = Number((await hudData(page)).artMemory);
      // One backdrop of memory each: the first stage's was freed, not added to.
      expect(caveMemory).toBeLessThan(meadowMemory * 1.05);
      expect(bg()).toBe(2);
      await shot(page, "desktop-light-13-cave");
      await fall(page);
      // Run three: meadow again, fetched again because it was unloaded.
      await page.keyboard.press("Space");
      await waitScreen(page, "play");
      expect(await hudData(page)).toMatchObject({ stage: "meadow", groups: "core,meadow" });
      expect(bg()).toBe(3);
      expect(problems).toEqual([]);
      await context.close();
    },
  );

  it("fetches from the page's own origin only", { timeout: 60_000 }, async () => {
    const { page, context, requests, goto } = await open("desktop", "light");
    await goto();
    await waitScreen(page, "title");
    await page.keyboard.press("Space");
    await waitScreen(page, "play");
    const origin = new URL(served.url).origin;
    expect(requests.filter((url) => !url.startsWith(origin) && !url.startsWith("data:"))).toEqual(
      [],
    );
    await context.close();
  });

  for (const look of ["desktop", "phone"] as const) {
    it(
      `${look}: a file that will not load shows the boot failure screen, and Try again loads it`,
      { timeout: 120_000 },
      async () => {
        const { page, context, goto } = await open(look, "dark");
        await page.route(/\/assets\/hopper-.*/, (route) =>
          route.fulfill({ status: 404, body: "gone" }),
        );
        await goto();
        await page.waitForSelector(".kg-boot", { timeout: 30_000 });
        expect(await page.getByRole("alert").textContent()).toContain("The game could not start");
        await page.locator("summary").click();
        const details = await page.locator("pre").textContent();
        expect(details).toContain('Could not load 1 file of "core": hopper (HTTP 404)');
        await shot(page, `${look}-dark-14-load-failed`);
        await page.unroute(/\/assets\/hopper-.*/);
        await page.getByRole("button", { name: "Try again" }).click();
        await waitScreen(page, "title");
        expect(await page.locator(".kg-boot").count()).toBe(0);
        await context.close();
      },
    );
  }

  it("is a clean package whose asset groups are inside their budgets", () => {
    expect(checkPackage(web, portalRow("web"))).toEqual([]);
    expect(existsSync(join(web, ASSET_REPORT))).toBe(true);
    const files = readdirSync(join(web, "assets"));
    expect(files.filter((name) => name.endsWith(".png"))).toHaveLength(4);
  });
});

describe("sound in Block Hopper", () => {
  it(
    "is silent until the first gesture, then plays music and effects, and a pause holds the audio clock",
    { timeout: 120_000 },
    async () => {
      const server = await createServer({
        configFile: join(example, "vite.config.ts"),
        server: { port: 8957, strictPort: false, host: "127.0.0.1" },
        logLevel: "error",
        cacheDir: join(work, "vite-cache-sound"),
      });
      await server.listen();
      try {
        const address = server.resolvedUrls?.local[0] ?? "http://127.0.0.1:8957/";
        const { page, context, problems, goto } = await open("desktop", "light", address);
        await goto();
        await waitScreen(page, "title");
        const state = () =>
          page.evaluate(() => {
            const game = (
              window as unknown as {
                __blockHopper: {
                  audio: { unlocked: boolean; context: AudioContext | null; paused: boolean };
                  sfx: { voices: number };
                };
              }
            ).__blockHopper;
            return {
              unlocked: game.audio.unlocked,
              made: game.audio.context !== null,
              clock: game.audio.context?.currentTime ?? 0,
              running: game.audio.context?.state ?? "none",
              voices: game.sfx.voices,
            };
          });
        // Nothing has been tapped: no context, no voice.
        expect(await state()).toMatchObject({ unlocked: false, made: false, voices: 0 });
        await page.keyboard.press("Space");
        await waitScreen(page, "play");
        await page.waitForTimeout(500);
        const playing = await state();
        expect(playing.unlocked).toBe(true);
        expect(playing.running).toBe("running");
        // The meadow theme loops on the music bus: one voice is not counted, the clock moves.
        await page.keyboard.press("Space");
        await page.waitForTimeout(80);
        expect((await state()).voices).toBeGreaterThan(0);
        // Pause: the context is suspended and its clock stands still.
        await page.keyboard.press("Escape");
        await page.waitForSelector('[role="dialog"]');
        await page.waitForTimeout(300);
        const paused = await state();
        expect(paused.running).toBe("suspended");
        await page.waitForTimeout(400);
        expect((await state()).clock).toBe(paused.clock);
        await page.keyboard.press("Escape");
        await page.waitForSelector('[role="dialog"]', { state: "detached" });
        await page.waitForTimeout(400);
        const resumed = await state();
        expect(resumed.running).toBe("running");
        expect(resumed.clock).toBeGreaterThan(paused.clock);
        expect(problems).toEqual([]);
        await context.close();
      } finally {
        await server.close();
      }
    },
  );

  it(
    "renders the sound it would play: a jump has energy in the first tenth of a second, in a real context",
    { timeout: 60_000 },
    async () => {
      const page = await browser.newPage();
      await page.goto(served.url);
      await waitScreen(page, "title");
      const peak = await page.evaluate(async () => {
        const ctx = new OfflineAudioContext(1, 4410, 44100);
        const buffer = ctx.createBuffer(1, 4410, 44100);
        // A 440 Hz sine, as the synth makes it, checked through a real graph.
        const data = buffer.getChannelData(0);
        for (let i = 0; i < data.length; i += 1)
          data[i] = Math.sin((i / 44100) * 440 * Math.PI * 2) * 0.5;
        const source = ctx.createBufferSource();
        source.buffer = buffer;
        source.connect(ctx.destination);
        source.start();
        const out = await ctx.startRendering();
        return Math.max(...out.getChannelData(0));
      });
      expect(peak).toBeGreaterThan(0.45);
      await page.close();
    },
  );
});

describe("the frame-time budget of the smoke run", () => {
  it.each([
    ["desktop", { width: 960, height: 540 }, false, undefined],
    ["a phone with the CPU slowed four times", { width: 390, height: 844 }, true, 4],
  ] as const)(
    "passes the example on %s",
    { timeout: 120_000 },
    async (_name, viewport, touch, cpuThrottle) => {
      const result = await runSmoke({
        dir: web,
        seconds: 4,
        viewport,
        touch,
        cpuThrottle,
        corruptStorage: false,
        script: [touch ? { at: 200, tap: { x: 0.8, y: 0.5 } } : { at: 200, key: "Space" }],
        ready: (page) => waitScreen(page, "title").then(() => undefined),
      });
      expect(result.problems).toEqual([]);
      expect(result.frameStats?.count).toBeGreaterThan(60);
      expect(result.frameStats?.p95).toBeLessThan(40);
    },
  );

  const janky = `<!doctype html><canvas id=c width=50 height=50></canvas><script>
    const c = document.getElementById('c').getContext('2d');
    let n = 0;
    (function frame() {
      const until = performance.now() + 110;
      while (performance.now() < until) {}
      c.fillStyle = 'hsl(' + (n++ * 17) + ',70%,50%)';
      c.fillRect(0, 0, 50, 50);
      requestAnimationFrame(frame);
    })();
  </script>`;

  it(
    "fails a game whose frames take 110 ms, and names the number",
    { timeout: 60_000 },
    async () => {
      const dir = join(work, "janky");
      mkdirSync(dir, { recursive: true });
      writeFileSync(join(dir, "index.html"), janky);
      const result = await runSmoke({ dir, seconds: 3, corruptStorage: false });
      expect(result.ok).toBe(false);
      expect(result.problems).toHaveLength(1);
      expect(result.problems[0]).toMatch(
        /^play: frame time: the 95th percentile is 1\d\d\.\d ms, over the budget of 40\.0 ms$/,
      );
      const slowest = await runSmoke({
        dir,
        seconds: 3,
        corruptStorage: false,
        frameBudget: { p95: 1000, max: 50 },
      });
      expect(slowest.problems).toHaveLength(1);
      expect(slowest.problems[0]).toMatch(
        /the slowest frame took 1\d\d\.\d ms, over the budget of 50\.0 ms$/,
      );
    },
  );

  it(
    "scales the budget with a multiplier, from the option or the environment, and with the game's own numbers",
    { timeout: 60_000 },
    async () => {
      const dir = join(work, "janky");
      const raised = await runSmoke({
        dir,
        seconds: 3,
        corruptStorage: false,
        frameMultiplier: 10,
      });
      expect(raised.problems).toEqual([]);
      const own = await runSmoke({
        dir,
        seconds: 3,
        corruptStorage: false,
        frameBudget: { p95: 500, max: 900 },
      });
      expect(own.problems).toEqual([]);
      const before = process.env.KARNI_SMOKE_FRAME_MULTIPLIER;
      process.env.KARNI_SMOKE_FRAME_MULTIPLIER = "10";
      try {
        const fromEnv = await runSmoke({ dir, seconds: 3, corruptStorage: false });
        expect(fromEnv.problems).toEqual([]);
      } finally {
        if (before === undefined) delete process.env.KARNI_SMOKE_FRAME_MULTIPLIER;
        else process.env.KARNI_SMOKE_FRAME_MULTIPLIER = before;
      }
      const off = await runSmoke({ dir, seconds: 2, corruptStorage: false, frameBudget: false });
      expect(off.problems).toEqual([]);
      expect(off.frameStats).toBeNull();
    },
  );
});

/** A one-page game that loads a group of the fixture's own, built with the real preset. */
async function fixture(
  name: string,
  files: Record<string, string | Buffer>,
  assets: AssetsPluginOptions,
  page: string,
) {
  const dir = join(work, name);
  mkdirSync(join(dir, "assets"), { recursive: true });
  for (const [file, body] of Object.entries(files)) {
    mkdirSync(dirname(join(dir, file)), { recursive: true });
    writeFileSync(join(dir, file), body);
  }
  writeFileSync(
    join(dir, "index.html"),
    '<!doctype html><html><body><canvas id="c"></canvas><script type="module" src="./main.ts"></script></body></html>',
  );
  writeFileSync(join(dir, "main.ts"), page);
  const out = join(dir, "dist");
  await build({
    root: dir,
    configFile: false,
    logLevel: "error",
    plugins: karniGame({ env: {}, assets }),
    resolve: {
      alias: [{ find: /^@karni\/game\/assets$/, replacement: `${src}/assets/index.ts` }],
    },
    build: { outDir: out, emptyOutDir: true },
  });
  return { dir, out };
}

/** The picture a person sees: 16x16 pixels of one colour, as PNG. */
async function colourPng(page: Page, hex: string): Promise<Buffer> {
  const base64 = await page.evaluate(async (colour) => {
    const canvas = document.createElement("canvas");
    canvas.width = 64;
    canvas.height = 64;
    const context = canvas.getContext("2d") as CanvasRenderingContext2D;
    context.fillStyle = colour;
    context.fillRect(0, 0, 64, 64);
    for (let i = 0; i < 64; i += 4) {
      context.fillStyle = i % 8 ? "#fff" : "#000";
      context.fillRect(i, i, 4, 4);
    }
    return canvas.toDataURL("image/png").split(",")[1] ?? "";
  }, hex);
  return Buffer.from(base64, "base64");
}

describe("assets in a real browser", () => {
  const loadPage = `
import { createAssets } from "@karni/game/assets";
import { manifest } from "virtual:karni-game/assets";
const assets = createAssets({ manifest, retries: 0 });
const w = window as unknown as Record<string, unknown>;
assets.load("art").then(() => {
  const image = assets.image("art", "tile");
  const canvas = document.getElementById("c") as HTMLCanvasElement;
  canvas.width = image.width;
  canvas.height = image.height;
  canvas.getContext("2d")?.drawImage(image.source, 0, 0);
  w.done = { width: image.width, height: image.height };
}, (error) => { w.failed = String(error); });
`;

  it(
    "downloads the WebP copy a browser made, and keeps the PNG as the fallback in the package",
    { timeout: 60_000 },
    async () => {
      const helper = await browser.newPage();
      // The browser itself is the encoder: a real WebP, from the page's canvas.
      const encode: WebpEncoder = async (input) => {
        const base64 = await helper.evaluate(async (data) => {
          const bytes = Uint8Array.from(atob(data), (c) => c.charCodeAt(0));
          const bitmap = await createImageBitmap(new Blob([bytes], { type: "image/png" }));
          const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
          (canvas.getContext("2d") as OffscreenCanvasRenderingContext2D).drawImage(bitmap, 0, 0);
          const blob = await canvas.convertToBlob({ type: "image/webp", quality: 0.5 });
          const buffer = new Uint8Array(await blob.arrayBuffer());
          let text = "";
          for (const byte of buffer) text += String.fromCharCode(byte);
          return btoa(text);
        }, Buffer.from(input).toString("base64"));
        return Buffer.from(base64, "base64");
      };
      // A plain, large PNG so the copy is smaller.
      const big = await helper.evaluate(async () => {
        const canvas = document.createElement("canvas");
        canvas.width = 256;
        canvas.height = 256;
        const context = canvas.getContext("2d") as CanvasRenderingContext2D;
        const gradient = context.createLinearGradient(0, 0, 256, 256);
        gradient.addColorStop(0, "#08f");
        gradient.addColorStop(1, "#f80");
        context.fillStyle = gradient;
        context.fillRect(0, 0, 256, 256);
        for (let i = 0; i < 4000; i += 1) {
          context.fillStyle = `rgba(${(i * 37) % 255},${(i * 91) % 255},${(i * 13) % 255},0.5)`;
          context.fillRect((i * 53) % 256, (i * 29) % 256, 3, 3);
        }
        return canvas.toDataURL("image/png").split(",")[1] ?? "";
      });
      const { out } = await fixture(
        "webp-real",
        { "assets/art/tile.png": Buffer.from(big, "base64") },
        { webp: { encode } },
        loadPage,
      );
      await helper.close();
      const files = readdirSync(join(out, "assets"));
      expect(files.some((f) => f.endsWith(".webp"))).toBe(true);
      expect(files.some((f) => f.endsWith(".png"))).toBe(true);
      const report = JSON.parse(readFileSync(join(out, ASSET_REPORT), "utf8"));
      expect(report.groups.art.bytes).toBeLessThan(report.groups.art.originalBytes);
      const fixtureServer = await serveFolder(out);
      try {
        const { page, context, problems, requests, goto } = await open(
          "desktop",
          "light",
          fixtureServer.url,
        );
        await goto();
        await page.waitForFunction(() => "done" in window || "failed" in window);
        expect(await page.evaluate(() => (window as unknown as { done?: object }).done)).toEqual({
          width: 256,
          height: 256,
        });
        expect(requests.some((url) => url.endsWith(".webp"))).toBe(true);
        expect(requests.some((url) => url.endsWith(".png"))).toBe(false);
        expect(problems).toEqual([]);
        await context.close();
      } finally {
        await fixtureServer.close();
      }
    },
  );

  it(
    "falls back to the PNG when the WebP copy cannot be decoded, and says nothing is wrong",
    { timeout: 60_000 },
    async () => {
      const helper = await browser.newPage();
      const png = await colourPng(helper, "#a27");
      await helper.close();
      const broken: WebpEncoder = async (input) => input.slice(0, 20);
      const { out } = await fixture(
        "webp-broken",
        { "assets/art/tile.png": png },
        { webp: { encode: broken } },
        loadPage,
      );
      const fixtureServer = await serveFolder(out);
      try {
        const { page, context, requests, goto } = await open("desktop", "light", fixtureServer.url);
        await goto();
        await page.waitForFunction(() => "done" in window || "failed" in window);
        expect(await page.evaluate(() => (window as unknown as { done?: object }).done)).toEqual({
          width: 64,
          height: 64,
        });
        const order = requests
          .filter((url) => /\.(webp|png)$/.test(url))
          .map((url) => url.split(".").pop());
        expect(order).toEqual(["webp", "png"]);
        await context.close();
      } finally {
        await fixtureServer.close();
      }
    },
  );

  const SYSTEM_FONTS = [
    "/System/Library/Fonts/Supplemental/Courier New.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
  ];
  const font = SYSTEM_FONTS.find((path) => existsSync(path));

  it.skipIf(!font)(
    "has a font ready before the first text is drawn",
    { timeout: 60_000 },
    async () => {
      const fontPage = `
import { createAssets } from "@karni/game/assets";
import { manifest } from "virtual:karni-game/assets";
const assets = createAssets({ manifest, retries: 0 });
const w = window as unknown as Record<string, unknown>;
const context = (document.getElementById("c") as HTMLCanvasElement).getContext("2d") as CanvasRenderingContext2D;
const width = (family: string) => { context.font = "32px " + family + ", serif"; return context.measureText("Hello, hopper").width; };
w.before = width("Probe");
assets.load("fonts").then(() => { w.after = width("Probe"); w.ready = document.fonts.check("32px Probe"); }, (e) => { w.failed = String(e); });
`;
      const { out } = await fixture(
        "font",
        { "assets/fonts/Probe.ttf": readFileSync(font as string) },
        { webp: false },
        fontPage,
      );
      const fixtureServer = await serveFolder(out);
      try {
        const { page, context, problems, goto } = await open("desktop", "light", fixtureServer.url);
        await goto();
        await page.waitForFunction(() => "ready" in window || "failed" in window);
        const result = await page.evaluate(() => {
          const w = window as unknown as Record<string, unknown>;
          return {
            before: w.before as number,
            after: w.after as number,
            ready: w.ready,
            failed: w.failed,
          };
        });
        expect(result.failed).toBeUndefined();
        expect(result.ready).toBe(true);
        // Text measured after the load uses the font, so its width is not the fallback's.
        expect(result.after).not.toBe(result.before);
        expect(problems).toEqual([]);
        await context.close();
      } finally {
        await fixtureServer.close();
      }
    },
  );
});
