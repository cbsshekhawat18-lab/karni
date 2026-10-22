import { describe, expect, it } from "vitest";
import { KARNI_THEME_SCRIPT, THEME_STORAGE_KEY } from "../src/index";
import { karniTheme } from "../vite-plugin";

describe("karniTheme (@karni/ui/vite)", () => {
  it("puts the theme script first in <head>, before anything paints", () => {
    const plugin = karniTheme();
    expect(plugin.name).toBe("karni-theme");
    expect(plugin.transformIndexHtml()).toEqual([
      { tag: "script", children: KARNI_THEME_SCRIPT, injectTo: "head-prepend" },
    ]);
  });

  it("reads the key ThemeProvider writes", () => {
    expect(KARNI_THEME_SCRIPT).toContain(`localStorage.getItem("${THEME_STORAGE_KEY}")`);
  });
});
