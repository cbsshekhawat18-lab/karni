/**
 * scripts/generate-manifest.mjs — static role scan (enforcement contract F11).
 *
 * Runs the real script as a child process: once against the package root
 * (asserting the shipped roles land in dist/manifest.json) and against tiny
 * throwaway fixtures (duplicate roles fail the build unless replace: true;
 * a non-literal first argument always fails).
 */
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

const packageRoot = process.cwd();
const script = resolve(packageRoot, "scripts/generate-manifest.mjs");

interface RunResult {
  status: number;
  stdout: string;
  stderr: string;
}

function runScript(root?: string): RunResult {
  const args = [script, ...(root ? ["--root", root] : [])];
  try {
    const stdout = execFileSync(process.execPath, args, { encoding: "utf8" });
    return { status: 0, stdout, stderr: "" };
  } catch (error) {
    const failure = error as { status?: number; stdout?: string; stderr?: string };
    return {
      status: failure.status ?? 1,
      stdout: failure.stdout ?? "",
      stderr: failure.stderr ?? "",
    };
  }
}

const cleanups: string[] = [];

afterEach(() => {
  for (const dir of cleanups.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

function makeFixture(files: Record<string, string>): string {
  const root = mkdtempSync(join(tmpdir(), "karni-manifest-"));
  cleanups.push(root);
  mkdirSync(join(root, "src"), { recursive: true });
  for (const [path, content] of Object.entries(files)) {
    writeFileSync(join(root, path), content);
  }
  return root;
}

const BARREL = 'export { Foo } from "./foo";\n';

describe("generate-manifest role scan", () => {
  it("emits the package's roles into dist/manifest.json", () => {
    const result = runScript();
    expect(result.stderr).toBe("");
    expect(result.status).toBe(0);
    expect(result.stdout).toMatch(/wrote \d+ components, \d+ hooks, 14 roles/);

    const manifest = JSON.parse(
      readFileSync(resolve(packageRoot, "dist/manifest.json"), "utf8"),
    ) as { components: string[]; hooks: string[]; roles: Record<string, string> };
    expect(manifest.components.length).toBeGreaterThan(0);
    expect(manifest.hooks.length).toBeGreaterThan(0);
    expect(manifest.roles).toEqual({
      "async-select": "ResourceSelect",
      "auth-guard": "AuthGuard",
      chart: "DataChart",
      "data-table": "ResourceTable",
      "detail-view": "ResourceDetail",
      "empty-state": "EmptyState",
      "file-upload": "FileUpload",
      "layout-shell": "Layout",
      "login-form": "LoginForm",
      modal: "Modal",
      "page-shell": "Page",
      "resource-form": "ResourceForm",
      stat: "Stat",
      toast: "Toaster",
    });
  });

  it("fails on duplicate role literals across distinct call sites", () => {
    const root = makeFixture({
      "src/index.ts": BARREL,
      "src/foo.ts": 'registerComponentRole("widget", "Foo");\nexport const Foo = 1;\n',
      "src/bar.ts": 'registerComponentRole("widget", "Bar");\nexport const Bar = 2;\n',
    });
    const result = runScript(root);
    expect(result.status).toBe(1);
    expect(result.stderr).toContain('duplicate component role "widget"');
    expect(result.stderr).toContain("src/foo.ts:1");
    expect(result.stderr).toContain("src/bar.ts:1");
  });

  it("accepts a duplicate that opts out with replace: true", () => {
    const root = makeFixture({
      "src/index.ts": BARREL,
      "src/foo.ts": 'registerComponentRole("widget", "Foo");\nexport const Foo = 1;\n',
      "src/bar.ts":
        'registerComponentRole("widget", "Bar", { replace: true, reason: "test fixture" });\n' +
        "export const Bar = 2;\n",
    });
    const result = runScript(root);
    expect(result.stderr).toBe("");
    expect(result.status).toBe(0);
    const manifest = JSON.parse(readFileSync(join(root, "dist/manifest.json"), "utf8")) as {
      roles: Record<string, string>;
    };
    expect(Object.keys(manifest.roles)).toEqual(["widget"]);
  });

  it("fails on a non-literal first argument", () => {
    const root = makeFixture({
      "src/index.ts": BARREL,
      "src/foo.ts":
        'const role = "widget";\nregisterComponentRole(role, "Foo");\nexport const Foo = 1;\n',
    });
    const result = runScript(root);
    expect(result.status).toBe(1);
    expect(result.stderr).toContain("must be a string literal");
    expect(result.stderr).toContain("src/foo.ts:2");
  });

  it("ignores test and story files when scanning", () => {
    const root = makeFixture({
      "src/index.ts": BARREL,
      "src/foo.ts": 'registerComponentRole("widget", "Foo");\nexport const Foo = 1;\n',
      "src/foo.test.ts": 'registerComponentRole("widget", "Clash");\n',
      "src/foo.stories.tsx": 'registerComponentRole("widget", "StoryClash");\n',
    });
    const result = runScript(root);
    expect(result.stderr).toBe("");
    expect(result.status).toBe(0);
  });
});
