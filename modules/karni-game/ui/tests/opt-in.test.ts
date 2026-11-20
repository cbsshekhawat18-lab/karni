// @vitest-environment node
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../../..");
const read = (path: string): string => readFileSync(join(repo, path), "utf8");

const SCAFFOLD = "templates/project/{{cookiecutter.project_slug}}/frontend/package.json";
// karni-cli's build copies templates/project here (packages/karni-cli/hatch_build.py).
// The copy exists once karni-cli is installed, not in a checkout that ran npm ci only.
const BUNDLED =
  "packages/karni-cli/karni_cli/_templates/project/{{cookiecutter.project_slug}}/frontend/package.json";

describe("the game add-on is opt-in on the npm side", () => {
  it("is in no plain project's frontend (the scaffold, and its copy in karni-cli when built)", () => {
    const templates = [SCAFFOLD, ...(existsSync(join(repo, BUNDLED)) ? [BUNDLED] : [])];
    for (const template of templates) {
      expect(read(template), template).not.toContain("@karni/game");
    }
  });

  it("is depended on by no other Karni npm package", () => {
    for (const manifest of [
      "packages/karni-ui/package.json",
      "modules/karni-commerce/ui/package.json",
    ]) {
      expect(read(manifest), manifest).not.toContain("@karni/game");
    }
  });

  it("has no runtime dependency of its own: engines, Vite and Playwright are optional peers", () => {
    const pkg = JSON.parse(read("modules/karni-game/ui/package.json")) as {
      dependencies?: Record<string, string>;
      peerDependencies: Record<string, string>;
      peerDependenciesMeta: Record<string, { optional?: boolean }>;
      sideEffects: boolean;
    };
    expect(pkg.dependencies ?? {}).toEqual({});
    expect(pkg.sideEffects).toBe(false);
    for (const peer of Object.keys(pkg.peerDependencies)) {
      expect(pkg.peerDependenciesMeta[peer]?.optional, peer).toBe(true);
    }
  });
});

describe("tree-shaking", () => {
  it("bundles only what a game imports", { timeout: 60_000 }, async () => {
    const { build } = await import("vite");
    const { mkdirSync, mkdtempSync, rmSync, writeFileSync } = await import("node:fs");
    const cache = join(repo, "modules/karni-game/ui/node_modules/.cache");
    mkdirSync(cache, { recursive: true });
    const dir = mkdtempSync(join(cache, "karni-game-shake-"));
    try {
      const entry = join(dir, "entry.ts");
      const src = join(repo, "modules/karni-game/ui/src/index.ts");
      writeFileSync(
        entry,
        `import { createRng } from ${JSON.stringify(src)};\nexport const roll = createRng(1).int(1, 6);\n`,
      );
      const output = await build({
        logLevel: "silent",
        configFile: false,
        build: {
          write: false,
          minify: false,
          lib: { entry, formats: ["es"], fileName: "entry" },
        },
      });
      const results = Array.isArray(output) ? output : [output];
      const code = results
        .flatMap((result) => ("output" in result ? result.output : []))
        .map((chunk) => ("code" in chunk ? chunk.code : ""))
        .join("\n");
      expect(code).toContain("function createRng");
      expect(code).not.toContain("X-Player-Token");
      expect(code).not.toContain("requestAnimationFrame");
      expect(code).not.toContain("AudioContext");
      expect(code.length).toBeLessThan(4000);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
