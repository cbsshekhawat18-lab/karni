/**
 * @karni/game/smoke: a browser smoke test for any web game. It boots the
 * game in a headless browser, plays it for a while with scripted input,
 * fails on any console error, page error or failed request, checks that the
 * canvas changed, and boots it again with corrupt storage.
 *
 * It needs Playwright (`npm install -D playwright` and
 * `npx playwright install chromium`), loaded only when the harness runs.
 */
import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer, type Server } from "node:http";
import { extname, join, normalize, resolve, sep } from "node:path";
import type { Browser, BrowserContext, LaunchOptions, Page } from "playwright";

/** One scripted input: at `at` ms after play starts, press or release a key, or tap. */
export type SmokeStep =
  | { at: number; key: string; action?: "down" | "up" | "press" }
  /** A tap at a point given as fractions of the canvas (0.5, 0.5 is its centre). */
  | { at: number; tap: { x: number; y: number } }
  /** Run anything on the page. */
  | { at: number; run: (page: Page) => Promise<void> };

/** The slowest frames a run may have, in ms, before any slow-machine multiplier. */
export interface FrameBudget {
  /** The 95th percentile of frame time. Default 40 (a steady 30 frames a second with room). */
  p95?: number;
  /** The slowest frame. Default 250: a pause for loading or a garbage collection is allowed, a freeze is not. */
  max?: number;
  /** Frames at the start of play that are not counted. Default 10. */
  warmup?: number;
}

/** The environment variable that scales every frame budget, for a slow CI runner: `KARNI_SMOKE_FRAME_MULTIPLIER=2`. */
export const FRAME_MULTIPLIER_ENV = "KARNI_SMOKE_FRAME_MULTIPLIER";
/** The environment variable that sets CPU throttling, as `KARNI_SMOKE_CPU_THROTTLE=4` (four times slower). */
export const CPU_THROTTLE_ENV = "KARNI_SMOKE_CPU_THROTTLE";

export interface FrameStats {
  /** Frames measured (after the warm-up). */
  count: number;
  p50: number;
  p95: number;
  max: number;
}

const DEFAULT_FRAME_BUDGET = { p95: 40, max: 250, warmup: 10 } as const;

/** The 50th and 95th percentile and the slowest of frame times, in ms. */
export function frameStats(frames: readonly number[], warmup = 0): FrameStats {
  const sorted = frames.slice(warmup).sort((a, b) => a - b);
  if (sorted.length === 0) return { count: 0, p50: 0, p95: 0, max: 0 };
  const at = (share: number): number =>
    sorted[Math.min(sorted.length - 1, Math.ceil(share * sorted.length) - 1)] ?? 0;
  return { count: sorted.length, p50: at(0.5), p95: at(0.95), max: sorted[sorted.length - 1] ?? 0 };
}

/** The findings of a run's frame times against a budget, scaled by `multiplier`. Empty when it is met. */
export function checkFrameBudget(
  stats: FrameStats,
  budget: FrameBudget = {},
  multiplier = 1,
): string[] {
  const p95 = (budget.p95 ?? DEFAULT_FRAME_BUDGET.p95) * multiplier;
  const max = (budget.max ?? DEFAULT_FRAME_BUDGET.max) * multiplier;
  const found: string[] = [];
  const ms = (value: number): string => `${value.toFixed(1)} ms`;
  if (stats.p95 > p95) {
    found.push(
      `frame time: the 95th percentile is ${ms(stats.p95)}, over the budget of ${ms(p95)}`,
    );
  }
  if (stats.max > max) {
    found.push(
      `frame time: the slowest frame took ${ms(stats.max)}, over the budget of ${ms(max)}`,
    );
  }
  return found;
}

function envNumber(name: string): number | undefined {
  const scope = globalThis as unknown as { process?: { env?: Record<string, string | undefined> } };
  const value = Number(scope.process?.env?.[name]);
  return Number.isFinite(value) && value > 0 ? value : undefined;
}

/** The multiplier of a run: the option, else the environment, else 1. */
export function frameMultiplier(option?: number): number {
  return option ?? envNumber(FRAME_MULTIPLIER_ENV) ?? 1;
}

export interface SmokeOptions {
  /** The game's address. Or give `dir`. */
  url?: string;
  /** A built game folder, served over http on a free port for the run. */
  dir?: string;
  /** How long to play, in seconds. Default 5. */
  seconds?: number;
  /** Scripted input. Default: nothing (the game just runs). */
  script?: readonly SmokeStep[];
  /** A selector for the game's canvas. Default "canvas". */
  canvas?: string;
  /** Boot a second time with every stored value replaced by broken data. Default true. */
  corruptStorage?: boolean;
  /** Console errors to ignore (a portal SDK's own noise in development). */
  ignore?: readonly RegExp[];
  viewport?: { width: number; height: number };
  /** Emulate a phone: touch events and a coarse pointer. */
  touch?: boolean;
  /** Your own assertions on the page after play; throw to fail. */
  check?: (page: Page, phase: "play" | "corrupt") => Promise<void>;
  /** Launch options for Chromium, or a browser of your own. */
  launch?: LaunchOptions;
  browser?: Browser;
  /**
   * Fail the run when its slowest frames pass a budget, measured with
   * `requestAnimationFrame` while the scripted input plays. Default the budget
   * of `FrameBudget`. `false` turns it off. Frame time is checked in the play
   * phase only.
   */
  frameBudget?: FrameBudget | false;
  /**
   * Scale the budget for a slower machine. Default `KARNI_SMOKE_FRAME_MULTIPLIER`
   * from the environment, else 1. The budget is scaled, so no wait is lengthened.
   */
  frameMultiplier?: number;
  /**
   * Slow the page's CPU by this factor (4 is a mid-range phone), through the
   * browser's own throttle. Default `KARNI_SMOKE_CPU_THROTTLE`, else none.
   */
  cpuThrottle?: number;
  /** Wait for this before play starts (a selector, or a function on the page). Default: the canvas. */
  ready?: string | ((page: Page) => Promise<void>);
}

export interface SmokePhase {
  consoleErrors: string[];
  pageErrors: string[];
  failedRequests: string[];
  /** The canvas showed something else at the end of play than at its start. */
  canvasChanged: boolean;
  /** Frame times of the scripted play, in ms (empty in the corrupt-storage phase). */
  frames: number[];
}

export interface SmokeResult {
  ok: boolean;
  play: SmokePhase;
  corrupt: SmokePhase | null;
  /** Frame time of the play phase against its budget (null when the budget is off). */
  frameStats: FrameStats | null;
  /** The storage keys the game wrote while playing. */
  storageKeys: string[];
  problems: string[];
}

const TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".webp": "image/webp",
  ".jpg": "image/jpeg",
  ".ogg": "audio/ogg",
  ".mp3": "audio/mpeg",
  ".wasm": "application/wasm",
};

/** Serve a folder over http on a free port (above 8900) until `close`. */
export async function serveFolder(dir: string): Promise<{ url: string; close(): Promise<void> }> {
  const root = resolve(dir);
  const server: Server = createServer((request, response) => {
    const path = decodeURIComponent((request.url ?? "/").split("?")[0] ?? "/");
    let file = normalize(join(root, path));
    if (file !== root && !file.startsWith(root + sep)) {
      response.writeHead(403).end();
      return;
    }
    if (existsSync(file) && statSync(file).isDirectory()) file = join(file, "index.html");
    if (!existsSync(file)) {
      response.writeHead(404).end();
      return;
    }
    response.writeHead(200, { "Content-Type": TYPES[extname(file)] ?? "application/octet-stream" });
    createReadStream(file).pipe(response);
  });
  for (let port = 8901 + Math.floor(Math.random() * 900); ; port += 1) {
    const listening = await new Promise<boolean>((done) => {
      server.once("error", () => done(false));
      server.listen(port, "127.0.0.1", () => done(true));
    });
    if (listening) {
      return {
        url: `http://127.0.0.1:${port}/`,
        close: () => new Promise((done) => server.close(() => done())),
      };
    }
    if (port > 9999) throw new Error("no free port between 8901 and 9999");
  }
}

async function canvasPicture(page: Page, selector: string): Promise<string> {
  return page.evaluate((query) => {
    const canvas = document.querySelector(query);
    return canvas instanceof HTMLCanvasElement ? canvas.toDataURL() : "";
  }, selector);
}

async function playPhase(
  context: BrowserContext,
  url: string,
  options: SmokeOptions,
  phase: "play" | "corrupt",
): Promise<{ result: SmokePhase; keys: string[]; page: Page }> {
  const page = await context.newPage();
  const result: SmokePhase = {
    consoleErrors: [],
    pageErrors: [],
    failedRequests: [],
    canvasChanged: false,
    frames: [],
  };
  const ignored = (text: string): boolean =>
    (options.ignore ?? []).some((pattern) => pattern.test(text));
  page.on("console", (message) => {
    if (message.type() === "error" && !ignored(message.text()))
      result.consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => result.pageErrors.push(error.message));
  page.on("requestfailed", (request) => {
    const line = `${request.url()} ${request.failure()?.errorText ?? ""}`.trim();
    if (!ignored(line)) result.failedRequests.push(line);
  });
  page.on("response", (response) => {
    if (response.status() >= 400 && !ignored(response.url())) {
      result.failedRequests.push(`${response.url()} ${response.status()}`);
    }
  });
  const selector = options.canvas ?? "canvas";
  const measure = phase === "play" && options.frameBudget !== false;
  if (measure) {
    // Runs before the game's own scripts. The list lives in a closure, not on window.
    await page.addInitScript(() => {
      const times: number[] = [];
      let last = 0;
      let on = false;
      const tick = (now: number): void => {
        if (on && last) times.push(now - last);
        last = now;
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
      Object.defineProperty(window, "__karniSmokeFrames", {
        value: {
          start: () => {
            times.length = 0;
            last = 0;
            on = true;
          },
          stop: () => {
            on = false;
            return times.slice();
          },
        },
      });
    });
  }
  const throttle = options.cpuThrottle ?? envNumber(CPU_THROTTLE_ENV);
  if (throttle && throttle > 1) {
    const session = await context.newCDPSession(page);
    await session.send("Emulation.setCPUThrottlingRate", { rate: throttle });
  }
  await page.goto(url, { waitUntil: "load" });
  if (typeof options.ready === "function") await options.ready(page);
  else await page.waitForSelector(options.ready ?? selector, { timeout: 15_000 });
  await page.waitForTimeout(300);
  const before = await canvasPicture(page, selector);
  const box = await page.locator(selector).first().boundingBox();
  const started = Date.now();
  if (measure) {
    await page.evaluate(() =>
      (window as unknown as { __karniSmokeFrames: { start(): void } }).__karniSmokeFrames.start(),
    );
  }
  const steps = [...(options.script ?? [])].sort((a, b) => a.at - b.at);
  for (const step of steps) {
    const wait = step.at - (Date.now() - started);
    if (wait > 0) await page.waitForTimeout(wait);
    if ("key" in step) {
      const action = step.action ?? "press";
      if (action === "down") await page.keyboard.down(step.key);
      else if (action === "up") await page.keyboard.up(step.key);
      else await page.keyboard.press(step.key);
    } else if ("tap" in step) {
      if (box) {
        const x = box.x + box.width * step.tap.x;
        const y = box.y + box.height * step.tap.y;
        if (options.touch) await page.touchscreen.tap(x, y);
        else await page.mouse.click(x, y);
      }
    } else {
      await step.run(page);
    }
  }
  const left = (options.seconds ?? 5) * 1000 - (Date.now() - started);
  if (left > 0) await page.waitForTimeout(left);
  if (measure) {
    result.frames = await page.evaluate(() =>
      (window as unknown as { __karniSmokeFrames: { stop(): number[] } }).__karniSmokeFrames.stop(),
    );
  }
  result.canvasChanged = before !== (await canvasPicture(page, selector));
  const keys = await page.evaluate(() => {
    try {
      return Object.keys(window.localStorage);
    } catch {
      return [];
    }
  });
  await options.check?.(page, phase);
  return { result, keys, page };
}

/** Run the smoke test. Resolves with every finding; `ok` is false when there is one. */
export async function runSmoke(options: SmokeOptions): Promise<SmokeResult> {
  const served = options.url ? null : options.dir ? await serveFolder(options.dir) : null;
  const url = options.url ?? served?.url;
  if (!url) throw new Error("runSmoke needs a url or a dir");
  const playwright = options.browser ? null : await import("playwright");
  const browser =
    options.browser ?? (await playwright?.chromium.launch({ headless: true, ...options.launch }));
  if (!browser) throw new Error("runSmoke could not start a browser");
  const problems: string[] = [];
  try {
    const context = await browser.newContext({
      viewport: options.viewport ?? { width: 960, height: 540 },
      hasTouch: options.touch ?? false,
      isMobile: options.touch ?? false,
    });
    const play = await playPhase(context, url, options, "play");
    let corrupt: SmokePhase | null = null;
    if (options.corruptStorage ?? true) {
      await play.page.evaluate(() => {
        try {
          for (const key of Object.keys(window.localStorage))
            window.localStorage.setItem(key, "{corrupt\u0000");
        } catch {
          // Blocked storage has nothing to corrupt.
        }
      });
      await play.page.close();
      corrupt = (await playPhase(context, url, options, "corrupt")).result;
    }
    for (const [name, phase] of [
      ["play", play.result],
      ["corrupt storage", corrupt],
    ] as const) {
      if (!phase) continue;
      for (const error of phase.consoleErrors) problems.push(`${name}: console error: ${error}`);
      for (const error of phase.pageErrors) problems.push(`${name}: page error: ${error}`);
      for (const request of phase.failedRequests)
        problems.push(`${name}: failed request: ${request}`);
      if (!phase.canvasChanged) problems.push(`${name}: the canvas did not change while playing`);
    }
    let stats: FrameStats | null = null;
    if (options.frameBudget !== false) {
      const budget = options.frameBudget ?? {};
      stats = frameStats(play.result.frames, budget.warmup ?? DEFAULT_FRAME_BUDGET.warmup);
      if (stats.count === 0) problems.push("play: no frames were measured (the page never drew)");
      for (const finding of checkFrameBudget(
        stats,
        budget,
        frameMultiplier(options.frameMultiplier),
      )) {
        problems.push(`play: ${finding}`);
      }
    }
    await context.close();
    return {
      ok: problems.length === 0,
      play: play.result,
      corrupt,
      frameStats: stats,
      storageKeys: play.keys,
      problems,
    };
  } finally {
    if (!options.browser) await browser.close();
    await served?.close();
  }
}
