import { defineConfig } from "@playwright/test";

// End-to-end suite against the running stack: the production build served by
// `vite preview` (proxying /api to Django on :8000), a Celery worker for the
// payment webhook, and the seeded database (`karni seed --reset --seed 42`).
// scripts/e2e.sh starts all of it; CI runs the same script.
export default defineConfig({
    testDir: "./e2e",
    timeout: 60_000,
    expect: { timeout: 10_000 },
    retries: process.env.CI ? 1 : 0,
    reporter: process.env.CI ? "github" : "list",
    use: {
        baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:4173",
        trace: "retain-on-failure",
    },
    webServer: {
        command: "npm run preview -- --strictPort",
        url: "http://127.0.0.1:4173",
        reuseExistingServer: !process.env.CI,
        timeout: 60_000,
    },
    projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
