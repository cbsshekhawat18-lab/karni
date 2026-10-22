/**
 * docs/ui.md is generated from the package manifest: it must never go stale.
 */
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { render } from "../scripts/generate-ui-doc.mjs";

const packageRoot = process.cwd();
const docs = resolve(packageRoot, "..", "..", "docs", "ui.md");

describe("docs/ui.md", () => {
  it.skipIf(!existsSync(docs))("matches a render of the freshly generated manifest", () => {
    execFileSync("node", [resolve(packageRoot, "scripts/generate-manifest.mjs")], {
      cwd: packageRoot,
    });
    const manifest = JSON.parse(
      readFileSync(resolve(packageRoot, "dist/manifest.json"), "utf8"),
    ) as Parameters<typeof render>[0];
    expect(readFileSync(docs, "utf8")).toBe(render(manifest));
  });

  it("documents every hook with its own line", () => {
    const manifest = {
      components: ["Page"],
      hooks: ["useAuth", "useSchema"],
      roles: { "page-shell": "Page" },
    };
    const page = render(manifest);
    expect(page).toContain("- `useAuth`: `{ user, status");
    expect(page).toContain("| `page-shell` | `Page` |");
  });
});
