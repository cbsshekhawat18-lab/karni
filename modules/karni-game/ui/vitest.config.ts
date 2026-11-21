import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const src = resolve(dirname(fileURLToPath(import.meta.url)), "src");

export default defineConfig({
  // The example game and the test fixtures import the package by its name, as a
  // game does: read it from src (as tsconfig.json's paths and the example's Vite
  // config do), so a fresh checkout tests before a build writes dist/.
  resolve: {
    alias: [
      { find: /^@karni\/game\/portals\/(.*)$/, replacement: `${src}/portal/adapters/$1.ts` },
      { find: /^@karni\/game\/scenes$/, replacement: `${src}/scenes/index.ts` },
      { find: /^@karni\/game\/sim$/, replacement: `${src}/sim/index.ts` },
      { find: /^@karni\/game\/ui$/, replacement: `${src}/ui/index.ts` },
      { find: /^@karni\/game$/, replacement: `${src}/index.ts` },
    ],
  },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.test.{ts,tsx}", "tests/**/*.test.{ts,tsx}"],
    restoreMocks: true,
  },
});
