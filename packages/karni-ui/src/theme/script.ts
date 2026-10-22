/**
 * The theme's pre-paint script, with no React: shared by ThemeProvider and
 * the `@karni/ui/vite` plugin, which runs in Node at build time.
 */

/** The localStorage key ThemeProvider keeps the user's choice under. */
export const THEME_STORAGE_KEY = "karni-theme";

/**
 * Inline script for index.html's <head>: applies the stored (or system) theme
 * before the first paint. Uses the default storage key. In a Vite app,
 * `karniTheme()` from `@karni/ui/vite` puts it there.
 */
export const KARNI_THEME_SCRIPT = `(function(){try{var t=localStorage.getItem("${THEME_STORAGE_KEY}");var d=t==="dark"||((t===null||t==="system")&&matchMedia("(prefers-color-scheme: dark)").matches);document.documentElement.classList.toggle("dark",d);document.documentElement.style.colorScheme=d?"dark":"light"}catch(e){}})();`;
