import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, type Browser, type Page } from "playwright";
import { build, createServer } from "vite";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { serveFolder } from "../src/smoke";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const example = join(root, "example", "block-hopper");
const cache = join(root, "node_modules", ".cache");
mkdirSync(cache, { recursive: true });
const work = mkdtempSync(join(cache, "karni-game-scenes-ui-"));
/** Screenshots of what a player sees, kept for a person to look at. */
const shots = process.env.KARNI_SHOTS ?? join(cache, "shots");
mkdirSync(shots, { recursive: true });
const axePath = createRequire(import.meta.url).resolve("axe-core/axe.min.js");

let browser: Browser;
let served: { url: string; close(): Promise<void> };

beforeAll(async () => {
  await build({
    configFile: join(example, "vite.config.ts"),
    build: { outDir: join(work, "web"), emptyOutDir: true },
    logLevel: "error",
  });
  served = await serveFolder(join(work, "web"));
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

async function open(look: Look, scheme: "light" | "dark", url = served.url, waitTitle = true) {
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
  page.on("console", (message) => {
    if (message.type() === "error") problems.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => problems.push(`page: ${error.message}`));
  page.on("requestfailed", (request) => problems.push(`request: ${request.url()}`));
  await page.goto(url);
  if (waitTitle) {
    await page.waitForFunction(() => document.getElementById("hud")?.dataset.screen === "title");
  }
  return { page, context, problems };
}

/** axe on the kit's layer, with colour contrast: a real browser has the layout it needs. */
async function axeViolations(page: Page): Promise<string[]> {
  await page.addScriptTag({ path: axePath });
  return page.evaluate(async () => {
    const axe = (window as unknown as { axe: typeof import("axe-core") }).axe;
    const result = await axe.run(".kg-root");
    return result.violations.map(
      (v) => `${v.id}: ${v.nodes.map((n) => `${n.html} (${n.failureSummary ?? ""})`).join(" | ")}`,
    );
  });
}

const noSidewaysScroll = (page: Page) =>
  page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
const shot = (page: Page, name: string) => page.screenshot({ path: join(shots, `${name}.png`) });
const stored = (page: Page, key: string) =>
  page.evaluate((k) => JSON.parse(window.localStorage.getItem(k) ?? "null"), key);
const hudScreen = (page: Page) =>
  page.evaluate(() => document.getElementById("hud")?.dataset.screen);

describe("Block Hopper's scenes and UI kit in a browser", () => {
  for (const look of ["desktop", "phone"] as const) {
    for (const scheme of ["light", "dark"] as const) {
      it(
        `${look}, ${scheme}: title, settings, play and pause are readable and pass axe`,
        { timeout: 120_000 },
        async () => {
          const { page, context, problems } = await open(look, scheme);
          const name = `${look}-${scheme}`;
          const touch = LOOKS[look].touch;
          const press = async (label: string) => {
            const button = page.getByRole("button", { name: label, exact: true });
            if (touch) await button.tap();
            else await button.click();
          };

          // Title: a DOM panel, the primary action has focus.
          await page.waitForSelector(".kg-screen");
          if (!touch) {
            expect(await page.evaluate(() => document.activeElement?.textContent)).toBe("Play");
          }
          expect(await noSidewaysScroll(page)).toBe(true);
          expect(await axeViolations(page)).toEqual([]);
          await shot(page, `${name}-1-title`);

          // Settings from the title: a dialog with its own focus.
          await press("Settings");
          await page.waitForSelector('[role="dialog"]');
          expect(await noSidewaysScroll(page)).toBe(true);
          expect(await axeViolations(page)).toEqual([]);
          const box = await page.locator(".kg-dialog").boundingBox();
          expect(box?.x).toBeGreaterThanOrEqual(0);
          expect((box?.x ?? 0) + (box?.width ?? 0)).toBeLessThanOrEqual(LOOKS[look].width);
          await shot(page, `${name}-2-settings`);
          await press("Close");
          await page.waitForSelector('[role="dialog"]', { state: "detached" });

          // Play: touch buttons show on a phone and not with a mouse.
          await press("Play");
          await page.waitForFunction(
            () => document.getElementById("hud")?.dataset.screen === "play",
          );
          await page.waitForTimeout(700);
          const shown = await page.locator(".kg-touch .kg-btn").first().isVisible();
          expect(shown).toBe(touch);
          expect(await axeViolations(page)).toEqual([]);
          await shot(page, `${name}-3-play`);

          // Pause over the run.
          if (touch) await press("Pause");
          else await page.keyboard.press("Escape");
          await page.waitForSelector('[role="dialog"]');
          expect(await page.evaluate(() => document.activeElement?.textContent)).toBe("Resume");
          expect(await axeViolations(page)).toEqual([]);
          await shot(page, `${name}-4-pause`);
          await press("Resume");
          await page.waitForSelector('[role="dialog"]', { state: "detached" });

          expect(problems).toEqual([]);
          await context.close();
        },
      );
    }
  }

  it(
    "is played by keyboard alone: Tab stays in the dialog, a key is remapped, Escape gives focus back",
    { timeout: 120_000 },
    async () => {
      const { page, context, problems } = await open("desktop", "light");
      await page.keyboard.press("Tab");
      expect(await page.evaluate(() => document.activeElement?.textContent)).toBe("Settings");
      await page.keyboard.press("Enter");
      await page.waitForSelector('[role="dialog"]');
      for (let n = 0; n < 30; n += 1) {
        await page.keyboard.press("Tab");
        expect(await page.evaluate(() => !!document.activeElement?.closest(".kg-dialog"))).toBe(
          true,
        );
      }
      // A slider moves with the arrow keys and the setting is saved.
      await page.getByRole("slider", { name: "Master volume" }).focus();
      await page.keyboard.press("ArrowLeft");
      await page.keyboard.press("ArrowLeft");
      // Remap Jump to J: the next key is the answer.
      await page.getByRole("button", { name: /^Jump:/ }).click();
      await page.keyboard.press("KeyJ");
      expect(await page.getByRole("button", { name: /^Jump:/ }).textContent()).toBe("Jump: J");
      await shot(page, "desktop-light-5-remapped");
      await page.keyboard.press("Escape");
      await page.waitForSelector('[role="dialog"]', { state: "detached" });
      expect(await page.evaluate(() => document.activeElement?.textContent)).toBe("Settings");
      const settings = await stored(page, "block-hopper.settings");
      expect(settings.data.master).toBeCloseTo(0.9);
      expect(settings.data.bindings.jump).toEqual(["KeyJ", "Pointer"]);
      // The remapped key starts a run, and the old one does not.
      await page.keyboard.press("Space");
      await page.waitForTimeout(150);
      expect(await hudScreen(page)).toBe("title");
      await page
        .locator("body")
        .click({ position: { x: 5, y: 5 } })
        .catch(() => undefined);
      await page.keyboard.press("KeyJ");
      await page.waitForFunction(() => document.getElementById("hud")?.dataset.screen === "play");
      expect(problems).toEqual([]);
      await context.close();
    },
  );

  it(
    "keeps the settings across a reload and applies them: colour-safe palette and mute",
    { timeout: 120_000 },
    async () => {
      const { page, context, problems } = await open("desktop", "dark");
      await page.getByRole("button", { name: "Settings", exact: true }).click();
      await page.getByRole("checkbox", { name: /Colour-safe palette/ }).check();
      await page.getByRole("checkbox", { name: /Reduced motion/ }).check();
      await page.getByRole("checkbox", { name: /Mute all sound/ }).check();
      await shot(page, "desktop-dark-6-colour-safe");
      expect(
        await page.evaluate(() =>
          document.querySelector(".kg-root")?.getAttribute("data-kg-palette"),
        ),
      ).toBe("safe");
      expect(await axeViolations(page)).toEqual([]);
      await page.getByRole("button", { name: "Close", exact: true }).click();
      await page.waitForTimeout(400);
      await page.reload();
      await page.waitForFunction(() => document.getElementById("hud")?.dataset.screen === "title");
      expect(
        await page.evaluate(() =>
          document.querySelector(".kg-root")?.getAttribute("data-kg-palette"),
        ),
      ).toBe("safe");
      expect(
        await page.evaluate(() =>
          document.querySelector(".kg-root")?.getAttribute("data-kg-motion"),
        ),
      ).toBe("reduced");
      // With reduced motion the title gives way to the run at once, with no fade.
      await page.getByRole("button", { name: "Play", exact: true }).click();
      await page.waitForFunction(() => document.getElementById("hud")?.dataset.screen === "play");
      expect(problems).toEqual([]);
      await context.close();
    },
  );

  for (const look of ["desktop", "phone"] as const) {
    for (const scheme of ["light", "dark"] as const) {
      it(
        `${look}, ${scheme}: a start that throws shows a readable screen, and Try again starts it`,
        { timeout: 120_000 },
        async () => {
          const dir = join(work, "boot-fixture");
          mkdirSync(dir, { recursive: true });
          writeFileSync(
            join(dir, "index.html"),
            `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Boot</title></head><body style="margin:0"><script type="module" src="./boot.ts"></script></body></html>`,
          );
          writeFileSync(
            join(dir, "boot.ts"),
            `import { guardBoot } from ${JSON.stringify(join(root, "src/ui/index.ts"))};
let attempts = 0;
void guardBoot(async () => {
  attempts += 1;
  if (attempts === 1) throw new Error("WebGL is not available in this browser");
  document.title = "started after " + attempts;
});`,
          );
          const out = join(work, `boot-${look}-${scheme}`);
          await build({
            root: dir,
            base: "./",
            build: { outDir: out, emptyOutDir: true },
            logLevel: "error",
            configFile: false,
          });
          const failed = await serveFolder(out);
          try {
            const { page, context, problems } = await open(look, scheme, failed.url, false);
            await page.waitForSelector(".kg-boot");
            expect(await page.getByRole("alert").textContent()).toContain(
              "The game could not start",
            );
            expect(await page.locator("pre").count()).toBe(1);
            await page.locator("summary").click();
            expect(await page.locator("pre").textContent()).toContain("WebGL is not available");
            expect(await noSidewaysScroll(page)).toBe(true);
            await page.addScriptTag({ path: axePath });
            const found = await page.evaluate(async () => {
              const axe = (window as unknown as { axe: typeof import("axe-core") }).axe;
              return (await axe.run(".kg-boot")).violations.map((v) => v.id);
            });
            expect(found).toEqual([]);
            await shot(page, `${look}-${scheme}-8-boot-failure`);
            await page.getByRole("button", { name: "Try again" }).click();
            await page.waitForFunction(() => document.title.startsWith("started after 2"));
            expect(await page.locator(".kg-boot").count()).toBe(0);
            expect(problems).toEqual([]);
            await context.close();
          } finally {
            await failed.close();
          }
        },
      );
    }
  }

  for (const [name, size] of [
    ["phone", { width: 390, height: 520 }],
    ["short desktop", { width: 1024, height: 360 }],
  ] as const) {
    it(
      `${name}: a dialog taller than the screen scrolls inside itself, with its title and Close in view`,
      { timeout: 120_000 },
      async () => {
        const { page, context, problems } = await open("phone", "dark");
        await page.setViewportSize(size);
        await page.getByRole("button", { name: "Settings", exact: true }).tap();
        await page.waitForSelector('[role="dialog"]');
        const measure = () =>
          page.evaluate(() => {
            const rect = (selector: string) =>
              document.querySelector(selector)?.getBoundingClientRect() ?? null;
            const body = document.querySelector<HTMLElement>(".kg-dialog .kg-body");
            return {
              dialog: rect(".kg-dialog"),
              title: rect(".kg-dialog h2"),
              close: rect(".kg-dialog .kg-actions .kg-btn"),
              bodyScrolls: !!body && body.scrollHeight > body.clientHeight,
              page: document.documentElement.scrollHeight <= window.innerHeight,
              height: window.innerHeight,
            };
          });
        const before = await measure();
        expect(before.bodyScrolls).toBe(true);
        expect(before.page).toBe(true);
        expect(before.dialog?.top).toBeGreaterThanOrEqual(0);
        expect(before.dialog?.bottom).toBeLessThanOrEqual(before.height);
        expect(before.title?.top).toBeGreaterThanOrEqual(0);
        expect(before.close?.bottom).toBeLessThanOrEqual(before.height);
        await shot(page, `${name.replace(" ", "-")}-dark-9-tall-dialog`);
        // Scroll the body to its end: the last row shows and Close has not moved.
        await page.evaluate(() => {
          const body = document.querySelector(".kg-dialog .kg-body");
          body?.scrollTo(0, body.scrollHeight);
        });
        const after = await measure();
        expect(after.close?.top).toBe(before.close?.top);
        expect(after.title?.top).toBe(before.title?.top);
        const reset = await page.getByRole("button", { name: "Reset controls" }).boundingBox();
        expect((reset?.y ?? 0) + (reset?.height ?? 0)).toBeLessThanOrEqual(
          (after.close?.top ?? 0) + 1,
        );
        expect(await axeViolations(page)).toEqual([]);
        await page.getByRole("button", { name: "Close", exact: true }).tap();
        await page.waitForSelector('[role="dialog"]', { state: "detached" });
        expect(problems).toEqual([]);
        await context.close();
      },
    );
  }

  it(
    "shows the dev overlay and pauses the loop under the pause menu in a dev server",
    { timeout: 120_000 },
    async () => {
      const server = await createServer({
        configFile: join(example, "vite.config.ts"),
        server: { port: 8947, strictPort: false, host: "127.0.0.1" },
        logLevel: "error",
        cacheDir: join(work, "vite-cache"),
      });
      await server.listen();
      try {
        const address = server.resolvedUrls?.local[0] ?? "http://127.0.0.1:8947/";
        const { page, context, problems } = await open("desktop", "light", address);
        await page.waitForSelector(".kg-dev");
        await page.waitForTimeout(600);
        const text = await page.locator(".kg-dev").textContent();
        expect(text).toMatch(/frame \d+\.\d ms \(max \d+\.\d\)/);
        expect(text).toMatch(/steps \d+/);
        expect(text).toMatch(/entities \d+/);
        await shot(page, "desktop-light-7-dev-overlay");
        await page.keyboard.press("Space");
        await page.waitForFunction(() => document.getElementById("hud")?.dataset.screen === "play");
        await page.waitForTimeout(300);
        await page.keyboard.press("Escape");
        await page.waitForSelector('[role="dialog"]');
        const paused = await page.evaluate(() => {
          const loop = (
            window as unknown as {
              __blockHopper: { loop: { paused: boolean; pauseReasons: Set<string> } };
            }
          ).__blockHopper.loop;
          return { paused: loop.paused, reasons: [...loop.pauseReasons] };
        });
        expect(paused).toEqual({ paused: true, reasons: ["menu"] });
        await page.keyboard.press("Escape");
        await page.waitForSelector('[role="dialog"]', { state: "detached" });
        expect(
          await page.evaluate(
            () =>
              (window as unknown as { __blockHopper: { loop: { paused: boolean } } }).__blockHopper
                .loop.paused,
          ),
        ).toBe(false);
        expect(problems).toEqual([]);
        await context.close();
      } finally {
        await server.close();
      }
    },
  );
});
