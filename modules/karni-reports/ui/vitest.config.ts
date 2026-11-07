import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const root = dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: {
    // @karni/ui's dist is not built in a fresh checkout; run its source
    // directly (the file: install stays in place for npm peer resolution).
    alias: {
      "@karni/ui": resolve(root, "../../../packages/karni-ui/src/index.ts"),
    },
    // The aliased sources live next to packages/karni-ui/node_modules — force
    // a single copy of react/react-query so hooks and context stay shared.
    dedupe: ["react", "react-dom", "@tanstack/react-query"],
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.{ts,tsx}", "tests/**/*.test.{ts,tsx}"],
    css: false,
    restoreMocks: true,
  },
});
