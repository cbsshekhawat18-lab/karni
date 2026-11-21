// @vitest-environment node
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, describe, expect, it } from "vitest";
import {
  ASSET_REPORT,
  CORE_GROUP,
  DEFAULT_GROUP_BUDGET,
  checkAssetReport,
  checkPackage,
  kindOfFile,
  manifestSource,
  portalRow,
  reportOf,
  scanAssets,
  typesSource,
  type WebpEncoder,
} from "../src/tooling";
import { karniGame } from "../src/tooling/vite";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const cache = join(root, "node_modules", ".cache");
mkdirSync(cache, { recursive: true });
const work = mkdtempSync(join(cache, "karni-game-assets-"));
afterAll(() => rmSync(work, { recursive: true, force: true }));

let n = 0;
function project(files: Record<string, string | Uint8Array>): string {
  const dir = join(work, `p${(n += 1)}`);
  for (const [name, body] of Object.entries(files)) {
    mkdirSync(dirname(join(dir, name)), { recursive: true });
    writeFileSync(join(dir, name), body);
  }
  return dir;
}

/** A stand-in for WebP: a quarter of the bytes, so it is always smaller. */
const quarter: WebpEncoder = async (input) => input.slice(0, Math.ceil(input.length / 4));
const big = new Uint8Array(4000).fill(7);
const other = new Uint8Array(4000).fill(9);

describe("scanning an assets folder", () => {
  it("groups by first folder, with `core` for loose files, and names without extension", async () => {
    const dir = project({
      "assets/logo.png": big,
      "assets/stage1/sky.png": big,
      "assets/stage1/ui/button.png": big,
      "assets/stage1/theme.ogg": "x",
      "assets/fonts/Inter-Bold.woff2": "font",
      "assets/data/levels.json": "[]",
      "assets/README.md": "not an asset",
    });
    const found = await scanAssets(join(dir, "assets"));
    expect(found.map((a) => `${a.group}/${a.name}:${a.kind}`)).toEqual([
      `data/levels:data`,
      `fonts/Inter-Bold:font`,
      `${CORE_GROUP}/logo:image`,
      "stage1/sky:image",
      "stage1/theme:sound",
      "stage1/ui/button:image",
    ]);
    expect(kindOfFile("a/b.WOFF2")).toBe("font");
    expect(kindOfFile("README.md")).toBeNull();
    expect(await scanAssets(join(dir, "missing"))).toEqual([]);
  });

  it("stops on two files that would share one name", async () => {
    const dir = project({ "assets/g/hero.png": "a", "assets/g/hero.jpg": "b" });
    await expect(scanAssets(join(dir, "assets"))).rejects.toThrow(
      /would both be "g\/hero": rename one/,
    );
  });

  it("writes a WebP copy of PNG and JPEG only when it is smaller, and caches it by content", async () => {
    const dir = project({
      "assets/g/a.png": big,
      "assets/g/b.jpg": big,
      "assets/g/c.gif": big,
      "assets/g/d.webp": big,
      "assets/g/e.svg": "<svg/>",
    });
    let calls = 0;
    const encode: WebpEncoder = async (input, file) => {
      calls += 1;
      return quarter(input, file);
    };
    const options = { encode, cacheDir: join(work, "webp-cache") };
    const found = await scanAssets(join(dir, "assets"), options);
    const by = Object.fromEntries(found.map((a) => [a.name, a]));
    expect(by.a?.webp?.bytes).toBe(1000);
    expect(by.a?.bytes).toBe(1000);
    expect(by.a?.originalBytes).toBe(4000);
    expect(by.b?.webp).toBeDefined();
    for (const name of ["c", "d", "e"]) expect(by[name]?.webp).toBeUndefined();
    expect(calls).toBe(2);
    await scanAssets(join(dir, "assets"), options);
    expect(calls).toBe(2);
    // Two files with equal bytes still get a copy each, named after the file.
    expect(readdirSync(join(work, "webp-cache"))).toHaveLength(2);
    // A "copy" that is no smaller is dropped, and the original stays.
    const same: WebpEncoder = async (input) => input;
    const kept = await scanAssets(join(dir, "assets"), {
      encode: same,
      cacheDir: join(work, "c2"),
    });
    expect(kept.find((a) => a.name === "a")?.webp).toBeUndefined();
  });
});

describe("the group budget", () => {
  const assets = [
    { group: "a", name: "x", file: "x", kind: "image" as const, originalBytes: 900, bytes: 600 },
    { group: "a", name: "y", file: "y", kind: "image" as const, originalBytes: 500, bytes: 500 },
    { group: "b", name: "z", file: "z", kind: "data" as const, originalBytes: 10, bytes: 10 },
  ];

  it("totals what each group downloads, against a number or a table", () => {
    expect(reportOf(assets, 1000).groups.a).toEqual({
      files: 2,
      bytes: 1100,
      originalBytes: 1400,
      budget: 1000,
    });
    const table = reportOf(assets, { a: 2000, "*": 50 });
    expect([table.groups.a?.budget, table.groups.b?.budget]).toEqual([2000, 50]);
    expect(reportOf(assets).groups.a?.budget).toBe(DEFAULT_GROUP_BUDGET);
  });

  it("fails a group over its budget and names it", () => {
    expect(checkAssetReport(reportOf(assets, 1100))).toEqual([]);
    const problems = checkAssetReport(reportOf(assets, 1000));
    expect(problems).toHaveLength(1);
    expect(problems[0]).toMatchObject({ rule: "asset-budget", file: ASSET_REPORT });
    expect(problems[0]?.message).toContain('"a" is 1100 bytes (2 files), over its budget of 1000');
  });

  it("is checked by the package check from the report in the package", () => {
    const dir = project({
      "index.html": "<!doctype html><html></html>",
      [ASSET_REPORT]: JSON.stringify(reportOf(assets, 1000)),
    });
    const problems = checkPackage(dir, portalRow("web"));
    expect(problems.map((p) => p.rule)).toEqual(["asset-budget"]);
    const fine = project({
      "index.html": "<!doctype html><html></html>",
      [ASSET_REPORT]: JSON.stringify(reportOf(assets, 5000)),
    });
    expect(checkPackage(fine, portalRow("web"))).toEqual([]);
    const broken = project({ "index.html": "<!doctype html>", [ASSET_REPORT]: "{" });
    expect(checkPackage(broken, portalRow("web")).map((p) => p.rule)).toEqual(["asset-budget"]);
  });
});

describe("the generated sources", () => {
  const assets = [
    {
      group: "stage1",
      name: "sky",
      file: "/p/assets/stage1/sky.png",
      kind: "image" as const,
      originalBytes: 9,
      bytes: 4,
      webp: { file: "/c/sky.webp", bytes: 4 },
    },
    {
      group: "core",
      name: "Inter-Bold",
      file: "/p/assets/Inter-Bold.woff2",
      kind: "font" as const,
      originalBytes: 9,
      bytes: 9,
    },
  ];

  it("imports each file as a URL so the bundler hashes it, and lists the allowed hosts and budgets", () => {
    const source = manifestSource(assets, ["a.example.com"], { stage1: 100 });
    expect(source).toContain('import f1 from "/p/assets/stage1/sky.png?url";');
    expect(source).toContain('import f2 from "/c/sky.webp?url";');
    expect(source).toContain('"sky": { kind: "image", url: f1, webp: f2, bytes: 4 }');
    expect(source).toContain('family: "Inter-Bold"');
    expect(source).toContain('export const assetHosts = ["a.example.com"];');
    expect(source).toContain('"stage1":100');
  });

  it("writes a declaration with the exact names", () => {
    const text = typesSource(assets);
    expect(text).toContain("interface KarniAssetGroups");
    expect(text).toContain('readonly "sky": AssetEntry;');
    expect(text).toContain('readonly "core"');
  });
});

describe("the Vite preset's manifest", () => {
  async function buildProject(
    files: Record<string, string | Uint8Array>,
    assets: object | false = {},
  ) {
    const dir = project({
      "index.html":
        '<!doctype html><html><body><script type="module" src="./main.ts"></script></body></html>',
      "main.ts": `import { manifest, assetHosts } from "virtual:karni-game/assets";
document.title = JSON.stringify({ manifest, assetHosts });`,
      ...files,
    });
    const { build } = await import("vite");
    await build({
      root: dir,
      configFile: false,
      logLevel: "silent",
      plugins: karniGame({
        env: {},
        assets: assets === false ? false : { webp: { encode: quarter }, ...assets },
      }),
      build: { outDir: join(dir, "dist"), emptyOutDir: true, minify: false, assetsInlineLimit: 0 },
    });
    return dir;
  }

  it("builds the manifest, hashes the files, writes the WebP copy and the report, and the package check passes", async () => {
    const dir = await buildProject(
      { "assets/stage1/sky.png": big, "assets/logo.png": other, "assets/data/level.json": "{}" },
      { budget: 10_000 },
    );
    const out = join(dir, "dist");
    const files = readdirSync(join(out, "assets"));
    expect(files.filter((f) => f.endsWith(".webp"))).toHaveLength(2);
    expect(files.filter((f) => f.endsWith(".png"))).toHaveLength(2);
    expect(files.filter((f) => f.endsWith(".json"))).toHaveLength(1);
    const js = readFileSync(
      join(out, "assets", files.find((f) => f.endsWith(".js")) as string),
      "utf8",
    );
    expect(js).toMatch(/"?sky"?: \{\s*kind: "image"/);
    expect(js).toMatch(/webp: /);
    // The bundler may print 1000 as 1e3.
    expect(js).toMatch(/bytes:\s*(1000|1e3)/);
    const report = JSON.parse(readFileSync(join(out, ASSET_REPORT), "utf8"));
    expect(report.groups.stage1).toEqual({
      files: 1,
      bytes: 1000,
      originalBytes: 4000,
      budget: 10000,
    });
    expect(checkPackage(out, portalRow("web"))).toEqual([]);
  }, 60_000);

  it("fails the package check when a group is over its budget", async () => {
    const dir = await buildProject({ "assets/stage1/sky.png": big }, { budget: { stage1: 500 } });
    const problems = checkPackage(join(dir, "dist"), portalRow("web"));
    expect(problems.map((p) => p.rule)).toEqual(["asset-budget"]);
  }, 60_000);

  it("keeps the originals when WebP is off, and writes types when asked", async () => {
    const dir = await buildProject(
      { "assets/g/a.png": big },
      { webp: false, types: "src/assets.d.ts" },
    );
    expect(readdirSync(join(dir, "dist", "assets")).some((f) => f.endsWith(".webp"))).toBe(false);
    expect(readFileSync(join(dir, "src/assets.d.ts"), "utf8")).toContain(
      'readonly "a": AssetEntry;',
    );
  }, 60_000);

  it("is off for a project without the folder, and with `assets: false`", async () => {
    const empty = await buildProject({});
    expect(existsSync(join(empty, "dist", ASSET_REPORT))).toBe(false);
    const off = await buildProject({ "assets/g/a.png": big }, false);
    expect(existsSync(join(off, "dist", ASSET_REPORT))).toBe(false);
  }, 60_000);
});
