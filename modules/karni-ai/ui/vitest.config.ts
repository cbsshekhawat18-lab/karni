import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const root = dirname(fileURLToPath(import.meta.url));
const karniUi = resolve(root, "../../../packages/karni-ui");

// ExtractButton renders @karni/ui's Modal and Tabs (Radix). Radix and the
// scroll lock under it live in packages/karni-ui/node_modules, and the scroll
// lock's default build requires React from there: a second copy of React. Their
// ES module builds go through Vite instead, where the dedupe below holds.
const ES_MODULE_BUILDS = [
  "react-remove-scroll",
  "react-remove-scroll-bar",
  "react-style-singleton",
  "use-callback-ref",
  "use-sidecar",
];

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: [
      // @karni/ui's dist is not built in a fresh checkout; run its source
      // directly (the file: install stays in place for npm peer resolution).
      { find: "@karni/ui", replacement: resolve(karniUi, "src/index.ts") },
      ...ES_MODULE_BUILDS.map((name) => ({
        find: new RegExp(`^${name}$`),
        replacement: resolve(karniUi, "node_modules", name, "dist/es2015/index.js"),
      })),
    ],
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
    server: {
      deps: { inline: [/@radix-ui\//, ...ES_MODULE_BUILDS.map((name) => new RegExp(name))] },
    },
  },
});
