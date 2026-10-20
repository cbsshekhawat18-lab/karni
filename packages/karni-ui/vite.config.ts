import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig, type PluginOption } from "vite";
import dts from "vite-plugin-dts";

const root = dirname(fileURLToPath(import.meta.url));

/**
 * dist/styles.css is a plain token sheet (no Tailwind directives), so it is
 * copied verbatim rather than run through the CSS pipeline.
 */
function copyStyles(): PluginOption {
  return {
    name: "karni:copy-styles",
    apply: "build",
    closeBundle() {
      mkdirSync(resolve(root, "dist"), { recursive: true });
      copyFileSync(resolve(root, "src/styles.css"), resolve(root, "dist/styles.css"));
      copyFileSync(resolve(root, "src/tailwind-v4.css"), resolve(root, "dist/tailwind-v4.css"));
    },
  };
}

export default defineConfig({
  plugins: [
    react(),
    dts({
      entryRoot: ".",
      include: ["src", "tailwind-preset.ts"],
      exclude: ["**/*.test.*", "**/*.stories.*", "tests/**", "dist/**"],
      tsconfigPath: resolve(root, "tsconfig.json"),
    }),
    copyStyles(),
  ],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: true,
    lib: {
      entry: {
        index: resolve(root, "src/index.ts"),
        "tailwind-preset": resolve(root, "tailwind-preset.ts"),
      },
      // Dual output: ESM for bundlers (`import`), CJS for `require()` consumers
      // (Jest, tailwind.config.cjs, older tooling). The package is
      // "type": "module", so CJS files MUST carry the .cjs extension.
      formats: ["es", "cjs"],
      fileName: (format, entryName) => `${entryName}.${format === "es" ? "js" : "cjs"}`,
    },
    rollupOptions: {
      // Externalize every bare import: peers and dependencies are resolved by
      // the consumer (bundler or Node's require).
      external: (id) => !id.startsWith(".") && !id.startsWith("/"),
      output: {
        // Shared code-split chunks keep Vite's lib default
        // (`[name]-[hash].js` / `.cjs`), which picks the right extension per
        // format; a custom pattern here would apply to both formats.
        exports: "named",
      },
    },
  },
});
