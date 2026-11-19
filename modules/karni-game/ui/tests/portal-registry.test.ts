import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { DEFAULT_SIZE_BUDGET, PORTALS, definePortals, portalRow } from "../src/tooling";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const pkg = JSON.parse(readFileSync(resolve(root, "package.json"), "utf8")) as {
  exports: Record<string, unknown>;
};

describe("the portal registry", () => {
  it("names each portal once", () => {
    const names = PORTALS.map((row) => row.name);
    expect(new Set(names).size).toBe(names.length);
    expect(names).toEqual(["web", "itch", "poki", "crazygames", "gamedistribution", "y8"]);
  });

  it("points every row at a published adapter that exports its factory", async () => {
    expect(pkg.exports["./portals/*"]).toBeDefined();
    for (const row of PORTALS) {
      const file = row.adapter.module.replace("@karni/game/portals/", "");
      const source = resolve(root, "src/portal/adapters", `${file}.ts`);
      expect(existsSync(source), row.name).toBe(true);
      const module = (await import(source)) as Record<string, unknown>;
      expect(typeof module[row.adapter.factory], row.name).toBe("function");
    }
  });

  it("keeps ids out: rows name the options a project's config fills, never a value", () => {
    for (const row of PORTALS) {
      for (const value of Object.values(row.options)) {
        expect(["web", "itch"]).toContain(value);
      }
    }
    expect(portalRow("gamedistribution").config).toEqual(["gameId"]);
    expect(portalRow("y8").config).toEqual(["appId"]);
  });

  it("lets every SDK row's hosts and markers identify it", () => {
    for (const row of PORTALS.filter((r) => r.headScript)) {
      expect(row.hosts).toContain(new URL(row.headScript ?? "").host);
      expect(row.markers.length).toBeGreaterThan(0);
    }
  });

  it("changes a row by name and adds a new one", () => {
    const rows = definePortals([
      { name: "poki", sizeBudget: 8 * 1024 * 1024 },
      {
        name: "arcade-site",
        title: "An arcade site",
        adapter: { module: "./my-adapter", factory: "arcade" },
      },
    ]);
    expect(portalRow("poki", rows).sizeBudget).toBe(8 * 1024 * 1024);
    expect(portalRow("poki").sizeBudget).toBe(DEFAULT_SIZE_BUDGET);
    expect(portalRow("arcade-site", rows).zip).toBe(true);
    expect(() => definePortals([{ name: "nameless" }])).toThrow(/needs a title and an adapter/);
    expect(() => portalRow("missing")).toThrow(/Known: web, itch/);
  });
});
