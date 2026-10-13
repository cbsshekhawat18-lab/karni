/**
 * The plugin, its docs links and rules.json (the source of docs/errors.md's
 * ESLint section) must agree: every rule documented, every link to its anchor.
 */
import { describe, expect, it } from "vitest";

import plugin from "./index.js";
import { docsUrl } from "./lib/docs.js";
import manifest from "./rules.json";

describe("eslint rules manifest", () => {
  const names = Object.keys(plugin.rules).sort();

  it("documents exactly the plugin's rules", () => {
    expect(manifest.map((entry) => entry.id).sort()).toEqual(names.map((name) => `karni/${name}`));
  });

  it("gives every rule a title, why and fix", () => {
    for (const entry of manifest) {
      expect(entry.title.length, entry.id).toBeGreaterThan(0);
      expect(entry.why.length, entry.id).toBeGreaterThan(0);
      expect(entry.fix.length, entry.id).toBeGreaterThan(0);
    }
  });

  it("links every rule to its docs/errors.md anchor", () => {
    for (const name of names) {
      expect(plugin.rules[name].meta.docs.url).toBe(docsUrl(name));
      expect(docsUrl(name)).toMatch(/errors\/#karni-[a-z-]+$/);
    }
  });
});
