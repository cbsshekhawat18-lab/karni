import { defineConfig } from "vitest/config";

/** The browser runs (`npm run test:smoke`): Chromium through Playwright, kept out of `npm test`. */
export default defineConfig({
  test: {
    environment: "node",
    include: ["tests-browser/**/*.test.ts"],
    testTimeout: 120_000,
    hookTimeout: 120_000,
    fileParallelism: false,
  },
});
