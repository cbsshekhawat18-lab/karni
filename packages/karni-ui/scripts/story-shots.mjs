#!/usr/bin/env node
/**
 * Screenshots of every Storybook story at phone, tablet and desktop widths,
 * light and dark: the raw material of a contact sheet.
 *
 *   npm run build-storybook -- -o storybook-static
 *   node scripts/story-shots.mjs storybook-static <out dir> [--widths 390,820,1280] [--only a,b]
 *
 * Writes <out>/<story id>--<width>--<theme>.png (full page) and
 * <out>/index.json listing every shot with its story title. With --only, the
 * shots taken replace those stories' entries in an existing index.json.
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { listStories, openStory, serveStatic } from "./lib/storybook.mjs";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PW ?? "playwright");

const [rootArg = "storybook-static", outArg = "story-shots"] = process.argv.slice(2);
const widthsArg = process.argv.indexOf("--widths");
const WIDTHS = (widthsArg === -1 ? "390,820,1280" : process.argv[widthsArg + 1])
  .split(",")
  .map(Number);
const THEMES = ["light", "dark"];
const root = path.resolve(rootArg);
const out = path.resolve(outArg);
mkdirSync(out, { recursive: true });

const stories = listStories(root);
const { base, close } = await serveStatic(root);
const browser = await chromium.launch();
const shots = [];
for (const width of WIDTHS) {
  const page = await browser.newPage({ viewport: { width, height: Math.round(width * 0.75) } });
  for (const story of stories) {
    for (const theme of THEMES) {
      const rendered = await openStory(page, base, story, theme);
      const file = `${story.id}--${width}--${theme}.png`;
      await page.screenshot({ path: path.join(out, file), fullPage: true, animations: "disabled" });
      shots.push({
        id: story.id,
        title: story.title,
        name: story.name,
        width,
        theme,
        file,
        rendered,
      });
    }
  }
  await page.close();
}
await browser.close();
close();
const indexFile = path.join(out, "index.json");
const retaken = new Set(stories.map((story) => story.id));
const kept =
  process.argv.includes("--only") && existsSync(indexFile)
    ? JSON.parse(readFileSync(indexFile, "utf8")).shots.filter((shot) => !retaken.has(shot.id))
    : [];
writeFileSync(
  indexFile,
  JSON.stringify({ widths: WIDTHS, themes: THEMES, shots: [...kept, ...shots] }, null, 2),
);
const blank = shots.filter((shot) => !shot.rendered);
console.log(
  `${shots.length} shots of ${stories.length} stories at ${WIDTHS.join("/")}px, ${THEMES.join(" and ")}; ${blank.length} rendered nothing${blank.length ? ": " + blank.map((s) => s.file).join(", ") : ""}.`,
);
