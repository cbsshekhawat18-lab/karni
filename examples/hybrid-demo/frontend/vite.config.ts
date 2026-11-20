import { fileURLToPath } from "node:url";
import { karniTheme } from "@karni/ui/vite";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// API and health requests from the dev server are proxied to Django:
// KARNI_API_PROXY when it is set (docker-compose sets http://django:8000 for
// its container), else runserver on 127.0.0.1 at KARNI_DEV_PORT (default
// 8000), the port `karni serve --local` uses. Both are read from the
// environment or the project's .env, so one KARNI_DEV_PORT line there moves
// Django and this proxy together.
export default defineConfig(({ mode }) => {
    const env = loadEnv(mode, fileURLToPath(new URL("..", import.meta.url)), "KARNI_");
    const target = env.KARNI_API_PROXY || `http://127.0.0.1:${env.KARNI_DEV_PORT || "8000"}`;
    const proxy = {
        "/api": { target, changeOrigin: true },
        "/health": { target, changeOrigin: true },
        "/readyz": { target, changeOrigin: true },
    };
    return {
        // karniTheme() applies the user's light/dark choice before the first paint.
        plugins: [react(), tailwindcss(), karniTheme()],
        server: { host: true, port: 5173, proxy },
        // `vite preview` serves the production build the same way (e2e suites, smoke checks).
        preview: { host: true, port: 4173, proxy },
    };
});
