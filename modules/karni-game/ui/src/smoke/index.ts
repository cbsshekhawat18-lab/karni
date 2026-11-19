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
  /** Wait for this before play starts (a selector, or a function on the page). Default: the canvas. */
  ready?: string | ((page: Page) => Promise<void>);
}

export interface SmokePhase {
  consoleErrors: string[];
  pageErrors: string[];
  failedRequests: string[];
  /** The canvas showed something else at the end of play than at its start. */
  canvasChanged: boolean;
}

export interface SmokeResult {
  ok: boolean;
  play: SmokePhase;
  corrupt: SmokePhase | null;
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
  await page.goto(url, { waitUntil: "load" });
  if (typeof options.ready === "function") await options.ready(page);
  else await page.waitForSelector(options.ready ?? selector, { timeout: 15_000 });
  await page.waitForTimeout(300);
  const before = await canvasPicture(page, selector);
  const box = await page.locator(selector).first().boundingBox();
  const started = Date.now();
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
    await context.close();
    return {
      ok: problems.length === 0,
      play: play.result,
      corrupt,
      storageKeys: play.keys,
      problems,
    };
  } finally {
    if (!options.browser) await browser.close();
    await served?.close();
  }
}
