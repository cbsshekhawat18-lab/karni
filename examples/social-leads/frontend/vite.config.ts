import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// API and health requests from the dev server are proxied to Django:
// `karni serve --local` (runserver on 127.0.0.1:8000) by default;
// docker-compose sets KARNI_API_PROXY=http://django:8000 for its container.
const target = process.env.KARNI_API_PROXY ?? "http://127.0.0.1:8000";
const proxy = {
    "/api": { target, changeOrigin: true },
    "/health": { target, changeOrigin: true },
};

export default defineConfig({
    plugins: [react()],
    server: { host: true, port: 5173, proxy },
    // `vite preview` serves the production build the same way (e2e suites, smoke checks).
    preview: { host: true, port: 4173, proxy },
});
