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

/**
 * The stories of a static build (its index.json), in Storybook's order.
 * `--only a,b` on the command line keeps the stories whose id contains one of
 * the words (`--only resourcetable,dropdownmenu`), to recheck after a fix.
 */
export function listStories(root, argv = process.argv) {
  const index = path.join(root, "index.json");
  if (!existsSync(index)) {
    throw new Error(`No Storybook build at ${root}: run npm run build-storybook -- -o ${root}`);
  }
  const stories = Object.values(JSON.parse(readFileSync(index, "utf8")).entries).filter(
    (entry) => entry.type === "story",
  );
  const flag = argv.indexOf("--only");
  if (flag === -1) return stories;
  const words = (argv[flag + 1] ?? "").split(",").filter(Boolean);
  const kept = stories.filter((story) => words.some((word) => story.id.includes(word)));
  if (kept.length === 0) throw new Error(`--only ${words.join(",")} matches no story id`);
  return kept;
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

/**
 * The story's `parameters` as the preview resolved them, read from the story's
 * render. Throws when the preview has no render for the story: a Storybook that
 * moved them must not quietly turn every `a11y` opt-out into nothing.
 */
export async function storyParameters(page) {
  const found = await page.evaluate(() => {
    const preview = window.__STORYBOOK_PREVIEW__;
    const id = new URLSearchParams(location.search).get("id");
    const render = (preview?.storyRenders ?? []).find((each) => each.id === id);
    return render ? { parameters: render.story?.parameters ?? {} } : null;
  });
  if (!found) throw new Error(`no story render in the preview for ${page.url()}`);
  return found.parameters;
}
