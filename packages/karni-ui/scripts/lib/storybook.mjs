/**
 * A static Storybook build as the browser sees it: serve it, list its
 * stories, open one in a theme. Shared by a11y-stories.mjs (axe) and
 * story-shots.mjs (screenshots).
 */
import { createReadStream, existsSync, readFileSync, statSync } from "node:fs";
import http from "node:http";
import path from "node:path";

const TYPES = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".mjs": "text/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".woff2": "font/woff2",
};

/** Serves `root` on a free loopback port; returns the base URL and a close function. */
export async function serveStatic(root) {
  const server = http.createServer((request, response) => {
    const url = new URL(request.url ?? "/", "http://localhost");
    let file = path.join(root, decodeURIComponent(url.pathname));
    if (!file.startsWith(root)) return void response.writeHead(403).end();
    if (existsSync(file) && statSync(file).isDirectory()) file = path.join(file, "index.html");
    if (!existsSync(file)) return void response.writeHead(404).end();
    response.writeHead(200, {
      "content-type": TYPES[path.extname(file)] ?? "application/octet-stream",
    });
    createReadStream(file).pipe(response);
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  return { base: `http://127.0.0.1:${server.address().port}`, close: () => server.close() };
}

/** The stories of a static build (its index.json), in Storybook's order. */
export function listStories(root) {
  const index = path.join(root, "index.json");
  if (!existsSync(index)) {
    throw new Error(`No Storybook build at ${root}: run npm run build-storybook -- -o ${root}`);
  }
  return Object.values(JSON.parse(readFileSync(index, "utf8")).entries).filter(
    (entry) => entry.type === "story",
  );
}

/**
 * Opens `story` in `theme` and waits for it to settle. Offline, slow and
 * pending states keep a request (or the load event) open on purpose, so every
 * wait is bounded. Resolves false when the story rendered nothing.
 */
export async function openStory(page, base, story, theme, { settle = 700 } = {}) {
  await page
    .goto(`${base}/iframe.html?id=${story.id}&viewMode=story&globals=theme:${theme}`, {
      waitUntil: "commit",
      timeout: 15000,
    })
    .catch((error) => {
      throw new Error(`${story.id} [${theme}] did not load: ${error.message}`);
    });
  await page.waitForLoadState("load", { timeout: 5000 }).catch(() => undefined);
  await page.waitForLoadState("networkidle", { timeout: 3000 }).catch(() => undefined);
  await page.waitForTimeout(settle);
  return page
    .waitForSelector("#storybook-root > *", { timeout: 5000 })
    .then(() => true)
    .catch(() => false);
}

/** The story's `parameters` as the preview resolved them (null when unavailable). */
export function storyParameters(page) {
  return page.evaluate(() => {
    const preview = window.__STORYBOOK_PREVIEW__;
    const id = new URLSearchParams(location.search).get("id");
    return preview?.storyStoreValue?.fromId?.(id)?.parameters ?? null;
  });
}
