/**
 * `@karni/ui/vite`: what a Vite app needs from @karni/ui at build time.
 *
 *   import { karniTheme } from "@karni/ui/vite";
 *   export default defineConfig({ plugins: [react(), karniTheme()] });
 *
 * Typed structurally, so it needs no `vite` types of its own.
 */
import { KARNI_THEME_SCRIPT } from "./src/theme/script";

/** One tag Vite's `transformIndexHtml` adds to index.html. */
export interface KarniHtmlTag {
  tag: "script";
  children: string;
  injectTo: "head-prepend";
}

/** The plugin object `karniTheme()` returns (a Vite `Plugin`). */
export interface KarniThemePlugin {
  name: "karni-theme";
  transformIndexHtml: () => KarniHtmlTag[];
}

/**
 * Puts KARNI_THEME_SCRIPT first in index.html's <head>, so the page paints
 * in the user's theme (stored, else the system's) before React starts.
 * Pair it with <ThemeProvider> around the app. Escape hatch: leave the
 * plugin out and inline KARNI_THEME_SCRIPT yourself (another storage key,
 * another framework).
 */
export function karniTheme(): KarniThemePlugin {
  return {
    name: "karni-theme",
    transformIndexHtml: () => [
      { tag: "script", children: KARNI_THEME_SCRIPT, injectTo: "head-prepend" },
    ],
  };
}
