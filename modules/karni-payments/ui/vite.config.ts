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
      formats: ["es"],
    },
    rollupOptions: {
      // Externalize every bare import: @karni/ui, react and react-query are
      // resolved by the consumer's bundler (ESM-only, mirrors @karni/ui).
      external: (id) => !id.startsWith(".") && !id.startsWith("/"),
      output: {
        entryFileNames: "[name].js",
        chunkFileNames: "chunks/[name]-[hash].js",
      },
    },
  },
});
