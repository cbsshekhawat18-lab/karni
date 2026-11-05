import { defineConfig } from "playwright/test";

// One test, against a stack that is already running (the job starts it, or `vite preview`
// and runserver do locally). See signin.spec.ts for the environment it reads.
const base = process.env.E2E_BASE_URL ?? "http://127.0.0.1:4173/";

export default defineConfig({
    testDir: ".",
    timeout: 60_000,
    expect: { timeout: 15_000 },
    retries: 0,
    reporter: process.env.CI ? [["github"], ["list"]] : "list",
    use: {
        // A trailing slash makes page.goto("products") relative to the app's path.
        baseURL: base.endsWith("/") ? base : `${base}/`,
        // Caddy's local CA signs the stack's certificate in CI.
        ignoreHTTPSErrors: true,
        trace: "retain-on-failure",
    },
    projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
