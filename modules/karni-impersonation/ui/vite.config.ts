import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import dts from "vite-plugin-dts";

const root = dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [
    react(),
    dts({
      entryRoot: ".",
      include: ["src"],
      exclude: ["**/*.test.*", "**/*.stories.*", "tests/**", "dist/**"],
      tsconfigPath: resolve(root, "tsconfig.json"),
      // The tsconfig paths point @karni/ui at monorepo SOURCE (local-dev
      // resolution); emitted declarations must keep the bare specifier.
      pathsToAliases: false,
    }),
  ],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: true,
    lib: {
      entry: { index: resolve(root, "src/index.ts") },
      // Dual ESM/CJS output, mirroring @karni/ui ("type": "module" => .cjs).
      formats: ["es", "cjs"],
      fileName: (format, entryName) => `${entryName}.${format === "es" ? "js" : "cjs"}`,
    },
    rollupOptions: {
      // Externalize every bare import: @karni/ui, react and react-query are
      // resolved by the consumer (bundler or Node's require).
      external: (id) => !id.startsWith(".") && !id.startsWith("/"),
      output: {
        // Chunks keep Vite's per-format lib default (`[name]-[hash].js|.cjs`).
        exports: "named",
      },
    },
  },
});
