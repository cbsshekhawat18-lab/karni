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
import { inflateRawSync } from "node:zlib";
import { afterAll, describe, expect, it } from "vitest";
import {
  PortalConfigError,
  apiHosts,
  checkPackage,
  checkSource,
  crc32,
  definePortals,
  envName,
  hostsIn,
  packagePortals,
  portalRow,
  resolveApiUrl,
  resolvePortal,
  zipFolder,
} from "../src/tooling";
import { main } from "../src/tooling/cli";
import { inlineIntoHtml, portalModuleSource } from "../src/tooling/vite";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const cache = join(root, "node_modules", ".cache");
mkdirSync(cache, { recursive: true });
const work = mkdtempSync(join(cache, "karni-game-tooling-"));
afterAll(() => rmSync(work, { recursive: true, force: true }));

let n = 0;
const folder = (files: Record<string, string>): string => {
  const dir = join(work, `pkg-${(n += 1)}`);
  for (const [name, text] of Object.entries(files)) {
    mkdirSync(dirname(join(dir, name)), { recursive: true });
    writeFileSync(join(dir, name), text);
  }
  return dir;
};
const page =
  '<!doctype html><html><head></head><body><script type="module" src="./assets/index.js"></script></body></html>';

describe("portal config", () => {
  it("names the environment variable of each option", () => {
    expect(envName("gamedistribution", "gameId")).toBe("KARNI_GAME_GAMEDISTRIBUTION_GAME_ID");
    expect(envName("y8", "appId")).toBe("KARNI_GAME_Y8_APP_ID");
  });

  it("takes ids from the project's config, then the environment, never the table", () => {
    expect(
      resolvePortal("gamedistribution", { env: { KARNI_GAME_GAMEDISTRIBUTION_GAME_ID: "env-id" } })
        .options,
    ).toEqual({ gameId: "env-id" });
    expect(
      resolvePortal("y8", {
        config: { y8: { appId: "cfg-app" } },
        env: { KARNI_GAME_Y8_APP_ID: "env-app", KARNI_GAME_Y8_AUTO_LOGIN: "false" },
      }).options,
    ).toEqual({ appId: "cfg-app", autoLogin: false });
    expect(resolvePortal("itch").options).toEqual({ name: "itch" });
  });

  it("stops a build that misses a required id and says where to set it", () => {
    expect(() => resolvePortal("gamedistribution")).toThrow(PortalConfigError);
    expect(() => resolvePortal("gamedistribution")).toThrow(/KARNI_GAME_GAMEDISTRIBUTION_GAME_ID/);
  });

  it("writes the portal module for the one adapter of the build", () => {
    const source = portalModuleSource(portalRow("poki"), {});
    expect(source).toContain('import { poki } from "@karni/game/portals/poki";');
    expect(source).toContain('export const portalName = "poki";');
    expect(source).not.toContain("crazygames");
    expect(source).toContain("export const gameApiUrl = null;");
    expect(portalModuleSource(portalRow("web"), {}, "https://api.example.com")).toContain(
      'export const gameApiUrl = "https://api.example.com";',
    );
  });

  it("names the game API a portal build calls: the option, else the environment", () => {
    expect(resolveApiUrl(undefined, {})).toBeNull();
    expect(resolveApiUrl(undefined, { KARNI_GAME_API_URL: "https://api.example.com/" })).toBe(
      "https://api.example.com",
    );
    expect(
      resolveApiUrl("https://play.example.com/backend", {
        KARNI_GAME_API_URL: "https://api.example.com",
      }),
    ).toBe("https://play.example.com/backend");
    expect(() => resolveApiUrl("api.example.com")).toThrow(PortalConfigError);
    expect(apiHosts("https://api.example.com:8443")).toEqual(["api.example.com"]);
    expect(apiHosts(null)).toEqual([]);
  });
});

describe("checkPackage", () => {
  const web = portalRow("web");
  const poki = portalRow("poki");

  it("passes a clean package", () => {
    const dir = folder({
      "index.html": page,
      "assets/index.js": 'const ns="http://www.w3.org/2000/svg";',
    });
    expect(checkPackage(dir, web)).toEqual([]);
  });

  it("finds every kind of problem", () => {
    const dir = folder({
      "index.html": '<html><script src="/assets/index.js"></script></html>',
      "assets/index.js": [
        'fetch("http://localhost:8000/api/")',
        'fetch("http://cdn.example.test/x.js")',
        'fetch("https://elsewhere.example.test/x.js")',
        "window.PokiSDK && 1",
        "window.__hopper = game;",
        "debugger;",
        'console.log("x")',
        'const apiKey = "abcdefghijklmnopqrstuvwxyz123456";',
      ].join("\n"),
    });
    const rules = checkPackage(dir, web).map((p) => p.rule);
    expect(new Set(rules)).toEqual(
      new Set([
        "absolute-path",
        "localhost",
        "insecure-url",
        "host",
        "other-portal",
        "debug-hook",
        "console",
        "secret",
      ]),
    );
  });

  it("lets a portal's own SDK host through, and applies its forbidden patterns", () => {
    const dir = folder({
      "index.html":
        '<script src="https://game-cdn.poki.com/scripts/v2/poki-sdk.js"></script>' + page,
      "assets/index.js": "PokiSDK.setDebug(true)",
    });
    expect(checkPackage(dir, poki).map((p) => p.rule)).toEqual(["forbidden"]);
  });

  it("holds a package to its size budget", () => {
    const dir = folder({ "index.html": page, "assets/big.bin": "x".repeat(2000) });
    const tight = definePortals([{ name: "web", sizeBudget: 1000 }]);
    expect(checkPackage(dir, portalRow("web", tight)).map((p) => p.rule)).toEqual(["size"]);
  });

  it("reports a missing index.html", () => {
    expect(checkPackage(folder({ "game.html": page }), web)[0]?.rule).toBe("index");
  });

  it("lists hosts without the namespace URLs libraries carry", () => {
    expect(hostsIn('a="http://www.w3.org/1999/xhtml" b="https://api.example.test/v1"')).toEqual([
      { host: "api.example.test", url: "https://api.example.test/v1" },
    ]);
  });
});

describe("checkSource", () => {
  it("finds portal ids typed into code and configured ids anywhere", () => {
    const dir = folder({
      "src/ads.ts": 'export const options = { gameId: "a1b2c3d4e5f6a7b8" };',
      "scripts/build.mjs": 'const id = "configured-id-77";',
      "src/fine.ts": "export const gameId = env.GAME_ID;",
    });
    const problems = checkSource([join(dir, "src"), join(dir, "scripts")], {
      ids: ["configured-id-77"],
    });
    expect(problems.map((p) => p.file?.split("/").pop())).toEqual(["ads.ts:1", "build.mjs:1"]);
  });
});

describe("zipFolder", () => {
  it("writes a zip with the files at its root that unpacks to the same bytes", () => {
    const dir = folder({ "index.html": page, "assets/index.js": "x".repeat(5000), "a.txt": "a" });
    const target = join(work, "out.zip");
    expect(zipFolder(dir, target).files).toBe(3);
    const zip = readFileSync(target);
    const end = zip.lastIndexOf(Buffer.from([0x50, 0x4b, 0x05, 0x06]));
    const count = zip.readUInt16LE(end + 10);
    let at = zip.readUInt32LE(end + 16);
    const entries: Record<string, string> = {};
    for (let i = 0; i < count; i += 1) {
      const method = zip.readUInt16LE(at + 10);
      const crc = zip.readUInt32LE(at + 16);
      const packed = zip.readUInt32LE(at + 20);
      const nameLength = zip.readUInt16LE(at + 28);
      const offset = zip.readUInt32LE(at + 42);
      const name = zip.subarray(at + 46, at + 46 + nameLength).toString();
      const localName = zip.readUInt16LE(offset + 26);
      const body = zip.subarray(offset + 30 + localName, offset + 30 + localName + packed);
      const data = method === 8 ? inflateRawSync(body) : body;
      expect(crc32(data)).toBe(crc);
      entries[name] = data.toString();
      at += 46 + nameLength;
    }
    expect(Object.keys(entries).sort()).toEqual(["a.txt", "assets/index.js", "index.html"]);
    expect(entries["assets/index.js"]).toBe("x".repeat(5000));
    expect(crc32(Buffer.from("123456789"))).toBe(0xcbf43926);
  });
});

describe("inlineIntoHtml", () => {
  it("puts scripts and styles into the page and drops preload links", () => {
    const html =
      '<head><link rel="modulepreload" href="./assets/dep.js"><link rel="stylesheet" crossorigin href="./assets/index.css"></head>' +
      '<body><script type="module" crossorigin src="./assets/index.js"></script></body>';
    const files = new Map([
      ["assets/index.js", { kind: "script" as const, code: 'console.info("</script>")' }],
      ["assets/index.css", { kind: "style" as const, code: "body{margin:0}" }],
    ]);
    const { html: out, inlined } = inlineIntoHtml(html, files);
    expect(inlined).toEqual(["assets/index.js", "assets/index.css"]);
    expect(out).toContain('<script type="module">console.info("<\\/script>")</script>');
    expect(out).toContain("<style>body{margin:0}</style>");
    expect(out).not.toContain("modulepreload");
  });
});

describe("the Vite preset and the per-portal packaging", { timeout: 120_000 }, () => {
  const fixture = join(root, "tests", "fixtures", "tiny-game");

  it("builds one package per portal, each with its SDK alone, checked and zipped", async () => {
    process.env.KARNI_GAME_GAMEDISTRIBUTION_GAME_ID = "test-gd-id";
    const out = join(work, "portals");
    const reports = await packagePortals({
      root: fixture,
      outDir: out,
      portals: ["web", "poki", "crazygames", "gamedistribution"],
    });
    delete process.env.KARNI_GAME_GAMEDISTRIBUTION_GAME_ID;
    for (const report of reports) expect(report.problems, report.portal).toEqual([]);
    const html = (portal: string) => readFileSync(join(out, portal, "index.html"), "utf8");
    expect(html("poki")).toContain('src="https://game-cdn.poki.com/scripts/v2/poki-sdk.js"');
    expect(html("web")).not.toContain("<script src=");
    expect(html("web")).toContain('src="./assets/');
    const gd = readdirSync(join(out, "gamedistribution", "assets"))
      .map((f) => readFileSync(join(out, "gamedistribution", "assets", f), "utf8"))
      .join("");
    expect(gd).toContain("test-gd-id");
    expect(gd).not.toContain("__tinyGame");
    expect(reports.find((r) => r.portal === "web")?.zip).toBeNull();
    expect(existsSync(join(out, "poki.zip"))).toBe(true);
    expect(existsSync(join(out, "crazygames.zip"))).toBe(false);
  });

  it("builds a portal package that calls the game API on the project's domain, and allows its host", async () => {
    const out = join(work, "api");
    const [report] = await packagePortals({
      root: fixture,
      outDir: out,
      portals: ["poki"],
      apiUrl: "https://api.block-hopper.example",
    });
    expect(report?.problems).toEqual([]);
    expect(process.env.KARNI_GAME_API_URL).toBeUndefined();
    const code = readdirSync(join(out, "poki", "assets"))
      .map((f) => readFileSync(join(out, "poki", "assets", f), "utf8"))
      .join("");
    expect(code).toContain("https://api.block-hopper.example");
    // The same package checked without the API's host: the host is refused.
    expect(checkPackage(join(out, "poki"), portalRow("poki")).map((p) => p.rule)).toEqual(["host"]);
    const lines: string[] = [];
    const args = ["check", join(out, "poki"), "--portal", "poki"];
    expect(await main(args, (line) => lines.push(line))).toBe(1);
    expect(
      await main([...args, "--allow-host", "api.block-hopper.example"], (l) => lines.push(l)),
    ).toBe(0);
  });

  it("fails a portal build whose id is missing, naming the variable", async () => {
    await expect(
      packagePortals({
        root: fixture,
        outDir: join(work, "missing"),
        portals: ["gamedistribution"],
      }),
    ).rejects.toThrow(/KARNI_GAME_GAMEDISTRIBUTION_GAME_ID/);
    // The command says the same in one line, with exit code 1 and no stack.
    const lines: string[] = [];
    const args = ["package", "--root", fixture, "--out", join(work, "missing-cli")];
    expect(await main([...args, "--portal", "gamedistribution"], (l) => lines.push(l))).toBe(1);
    expect(lines).toEqual([expect.stringMatching(/^FAIL .*KARNI_GAME_GAMEDISTRIBUTION_GAME_ID/)]);
  });

  it("makes a single-file build that needs no other file", async () => {
    process.env.TINY_SINGLE = "1";
    const out = join(work, "single");
    const [report] = await packagePortals({ root: fixture, outDir: out, portals: ["itch"] });
    delete process.env.TINY_SINGLE;
    expect(report?.problems).toEqual([]);
    expect(readdirSync(join(out, "itch"))).toEqual(["index.html"]);
    const html = readFileSync(join(out, "itch", "index.html"), "utf8");
    expect(html).toContain('<script type="module">');
    expect(html).toContain("<style>");
  });
});

describe("the karni-game command", () => {
  it("lists the portals and checks a package", async () => {
    const lines: string[] = [];
    expect(await main(["portals"], (line) => lines.push(line))).toBe(0);
    expect(lines.join("\n")).toMatch(/gamedistribution\s+GameDistribution needs gameId/);
    const dir = folder({ "index.html": page, "assets/index.js": "window.__x = 1;" });
    expect(await main(["check", dir, "--portal", "web"], (line) => lines.push(line))).toBe(1);
    expect(lines.at(-1)).toContain("debug-hook");
    expect(await main(["nonsense"], () => undefined)).toBe(2);
  });
});
