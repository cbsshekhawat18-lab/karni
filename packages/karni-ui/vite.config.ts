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
      formats: ["es"],
    },
    rollupOptions: {
      // Externalize every bare import: peers and dependencies are resolved by
      // the consumer's bundler (the package is ESM-only, documented in README).
      external: (id) => !id.startsWith(".") && !id.startsWith("/"),
      output: {
        entryFileNames: "[name].js",
        chunkFileNames: "chunks/[name]-[hash].js",
      },
    },
  },
});
