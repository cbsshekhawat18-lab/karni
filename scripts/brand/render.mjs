// Rasterise the brand SVGs with Chromium (Playwright) and build the contact sheet.
//
//   node scripts/brand/render.mjs assets/brand scripts/brand/out
//
// Writes favicon-16/32/48.png, apple-touch-icon-180.png, the avatar set
// (avatar-400/460/512/1024.png full-bleed black, plus -transparent variants)
// and social-1280x640.png into the assets folder; a 16px side-by-side
// comparison, the brand contact sheet and the avatar contact sheet (HTML +
// screenshot) into the out folder. Playwright comes from the EventHub
// frontend's node_modules (the repo's only browser dependency).
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { createRequire } from "node:module";

const require = createRequire(resolve("examples/eventhub/frontend/package.json"));
const { chromium } = require("playwright");

const [assets, out] = process.argv.slice(2).map((p) => resolve(p));
mkdirSync(out, { recursive: true });

const svg = (name) => readFileSync(resolve(assets, name), "utf8");
const dataUri = (name) => `data:image/svg+xml;utf8,${encodeURIComponent(svg(name))}`;
// Embedded as a data URI: a page from setContent() has no origin and cannot load file:// fonts.
const fontData = `data:font/ttf;base64,${readFileSync(resolve(process.env.KARNI_BRAND_FONT ?? "scripts/brand/Jost.ttf")).toString("base64")}`;

const browser = await chromium.launch();

async function shoot(html, { width, height, path, omitBackground = false, scale = 1, fullPage = false }) {
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: scale });
  await page.setContent(html);
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path, omitBackground, fullPage });
  await page.close();
}

const flat = (name, size) =>
  `<html><body style="margin:0;background:transparent"><img src="${dataUri(name)}" width="${size}" height="${size}" style="display:block"></body></html>`;

// --- icons ---------------------------------------------------------------------
for (const size of [16, 32]) {
  await shoot(flat("karni-mark-simple.svg", size), { width: size, height: size, path: resolve(assets, `favicon-${size}.png`), omitBackground: true });
}
await shoot(flat("karni-mark.svg", 48), { width: 48, height: 48, path: resolve(assets, "favicon-48.png"), omitBackground: true });
await shoot(
  `<html><body style="margin:0;background:#000"><img src="${dataUri("karni-mark.svg")}" width="180" height="180" style="display:block"></body></html>`,
  { width: 180, height: 180, path: resolve(assets, "apple-touch-icon-180.png") },
);

// --- social preview --------------------------------------------------------------
const social = `<html><head><style>
@font-face{font-family:Jost;src:url("${fontData}") format("truetype");font-weight:100 900}
body{margin:0;width:1280px;height:640px;background:#000;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:28px;font-family:Jost,sans-serif}
img{height:230px;width:auto}
p{margin:0;color:#fff;opacity:.85;font-size:36px;font-weight:400;letter-spacing:.01em}
</style></head><body><img src="${dataUri("karni-horizontal-dark.svg")}"><p>Django + React, built so AI agents extend it instead of rewriting it.</p></body></html>`;
await shoot(social, { width: 1280, height: 640, path: resolve(assets, "social-1280x640.png") });

// --- avatars ---------------------------------------------------------------------
// Platforms crop avatars to a circle (GitHub, npm, X) or a rounded square (Docker
// Hub, Gravatar) and show them as small as 40px. The full-bleed files put the
// mark on a solid black square so a circular crop is a black disc, not a cut
// irregular ground; at 86% of the canvas the ground's bounding box sits just
// inside the inscribed circle. The transparent variants are the mark itself,
// for surfaces that show the avatar uncropped on their own background.
const AVATAR_SOURCE = "karni-mark.svg";
const AVATAR_SIZES = [400, 460, 512, 1024];
const avatar = (name, size) =>
  `<html><body style="margin:0;width:${size}px;height:${size}px;background:#000;display:flex;align-items:center;justify-content:center"><img src="${dataUri(name)}" width="${Math.round(size * 0.86)}" height="${Math.round(size * 0.86)}" style="display:block"></body></html>`;
for (const size of AVATAR_SIZES) {
  await shoot(avatar(AVATAR_SOURCE, size), { width: size, height: size, path: resolve(assets, `avatar-${size}.png`) });
  await shoot(flat(AVATAR_SOURCE, size), { width: size, height: size, path: resolve(assets, `avatar-${size}-transparent.png`), omitBackground: true });
}

// --- avatar contact sheet: what the platforms will actually show -----------------------
// avatar-400.png as uploaded, shown square and circle-cropped at 40/80/200/400 on
// white, GitHub dark and GitHub light; the transparent variant beside it; and a
// 40px row comparing the full mark with the simple variant as the avatar source,
// which is the decision the brand README records.
const avatarPng = (name) => `data:image/png;base64,${readFileSync(resolve(assets, name)).toString("base64")}`;
const avatarSizes = [40, 80, 200, 400];
const avatarGrounds = [["white", "#fff", "#000"], ["GitHub dark", "#0d1117", "#e6edf3"], ["GitHub light", "#f6f8fa", "#1f2328"]];
const avatarCell = (src, size, round) =>
  `<img src="${src}" width="${size}" height="${size}" style="display:block;${round ? "border-radius:50%" : ""}">`;
const simpleAvatar400 = resolve(out, "avatar-400-simple-candidate.png");
await shoot(avatar("karni-mark-simple.svg", 400), { width: 400, height: 400, path: simpleAvatar400 });
const simpleSrc = `data:image/png;base64,${readFileSync(simpleAvatar400).toString("base64")}`;
const avatarRows = [
  ["avatar-400.png, square", avatarPng("avatar-400.png"), false],
  ["avatar-400.png, circle crop", avatarPng("avatar-400.png"), true],
  ["avatar-400-transparent.png", avatarPng("avatar-400-transparent.png"), false],
];
const avatarSheet = `<html><head><style>
body{margin:0;font:13px system-ui;background:#eee}
section{padding:12px 16px}
h2{margin:0 0 8px;font-size:14px}
table{border-collapse:collapse}
td,th{padding:8px 12px;vertical-align:bottom;text-align:left}
th{font-weight:500}
</style></head><body>
${avatarGrounds.map(([label, bg, fg]) => `<section style="background:${bg};color:${fg}"><h2>on ${label} (${bg})</h2><table><tr><th></th>${avatarSizes.map((s) => `<th>${s}px</th>`).join("")}</tr>
${avatarRows.map(([title, src, round]) => `<tr><th>${title}</th>${avatarSizes.map((s) => `<td>${avatarCell(src, s, round)}</td>`).join("")}</tr>`).join("")}
<tr><th>40px source check: full mark vs simple variant (circle crop)</th><td>${avatarCell(avatarPng("avatar-400.png"), 40, true)}</td><td>${avatarCell(simpleSrc, 40, true)}</td><td colspan="2">${avatarCell(avatarPng("avatar-400.png"), 80, true)} ${avatarCell(simpleSrc, 80, true)}</td></tr>
</table></section>`).join("")}
</body></html>`;
writeFileSync(resolve(out, "avatar-contact-sheet.html"), avatarSheet);
await shoot(avatarSheet, { width: 1100, height: 600, path: resolve(out, "avatar-contact-sheet.png"), fullPage: true });

// --- 16px comparison, upscaled with nearest-neighbour so pixels can be judged ------------
const compare = `<html><body style="margin:0;background:#fff;display:flex;gap:24px;padding:16px;align-items:flex-end;font:12px system-ui">
${["karni-mark.svg", "karni-mark-simple.svg"].map((n) => `<figure style="margin:0;text-align:center"><img src="${dataUri(n)}" width="16" height="16" style="display:block;margin:0 auto 6px"><img src="${dataUri(n)}" width="16" height="16" style="display:block;width:128px;height:128px;image-rendering:pixelated"><figcaption>${n} @16px (actual, then ×8)</figcaption></figure>`).join("")}
</body></html>`;
await shoot(compare, { width: 420, height: 200, path: resolve(out, "compare-16px.png") });

// --- contact sheet ---------------------------------------------------------------
const variants = ["karni-mark.svg", "karni-mark-simple.svg", "karni-mark-light.svg", "karni-mark-mono.svg", "karni-horizontal.svg", "karni-horizontal-dark.svg"];
const sizes = [16, 32, 64, 256, 512];
const grounds = [["white", "#fff", "#000"], ["black", "#000", "#fff"], ["mid-grey", "#808080", "#000"]];
const cell = (name, size, color) => {
  const mono = name.includes("mono");
  return `<img src="${dataUri(name)}" height="${size}" style="display:block;${mono ? `color:${color}` : ""}">`;
};
const sheet = `<html><head><style>
body{margin:0;font:13px system-ui;background:#eee}
section{padding:12px 16px}
h2{margin:0 0 8px;font-size:14px}
table{border-collapse:collapse}
td,th{padding:8px 12px;vertical-align:bottom;text-align:left}
th{font-weight:500}
</style></head><body>
${grounds.map(([label, bg, fg]) => `<section style="background:${bg};color:${fg}"><h2>on ${label}</h2><table><tr><th></th>${sizes.map((s) => `<th>${s}px</th>`).join("")}</tr>
${variants.map((v) => `<tr><th>${v}</th>${sizes.map((s) => `<td>${cell(v, s, fg)}</td>`).join("")}</tr>`).join("")}
</table></section>`).join("")}
</body></html>`;
writeFileSync(resolve(out, "contact-sheet.html"), sheet);
await shoot(sheet, { width: 2300, height: 1200, path: resolve(out, "contact-sheet.png"), fullPage: true });
await browser.close();

// --- the mark as data for @karni/ui's <KarniMark/> and the docs site ---------------------
const paths = (name) => [...svg(name).matchAll(/<path fill="([^"]+)" d="([^"]+)"\/>/g)].map(([, fill, d]) => ({ fill, d }));
const simpleBody = svg("karni-mark-simple.svg").replace(/^[\s\S]*?>\n/, "").replace(/\n<\/svg>\n$/, "");
const ts = `// Generated by scripts/brand/render.mjs from assets/brand/ — do not edit.
export const MARK_VIEWBOX = "0 0 1000 1000";
/** The full mark: ground, rings, strokes. */
export const MARK_PATHS: ReadonlyArray<{ readonly fill: string; readonly d: string }> = ${JSON.stringify(paths("karni-mark.svg"), null, 2)};
/** The small-size variant's SVG body (use at 32px and below). */
export const MARK_SIMPLE_BODY = ${JSON.stringify(simpleBody)};
`;
writeFileSync(resolve("packages/karni-ui/src/components/brand/mark-paths.ts"), ts);
for (const name of ["karni-mark.svg", "karni-mark-light.svg", "karni-mark-mono.svg", "favicon.svg", "social-1280x640.png", "karni-horizontal.svg", "karni-horizontal-dark.svg"]) {
  mkdirSync(resolve("docs/assets/brand"), { recursive: true });
  writeFileSync(resolve("docs/assets/brand", name), readFileSync(resolve(assets, name)));
}
console.log("rendered", out);
