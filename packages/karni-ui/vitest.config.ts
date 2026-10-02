import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: [
      "src/**/*.test.{ts,tsx}",
      "tests/**/*.test.{ts,tsx}",
      // The ESLint plugin is plain ESM with no build step; its RuleTester
      // suites are .mjs so they stay outside the library tsconfig.
      "eslint-plugin/**/*.test.mjs",
    ],
    css: false,
    restoreMocks: true,
  },
});
