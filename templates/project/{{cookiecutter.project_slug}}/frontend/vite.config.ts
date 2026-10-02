import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In docker-compose, "django" resolves to the backend container; API and
// health requests from the dev server are proxied to it.
export default defineConfig({
    plugins: [react()],
    server: {
        host: true,
        port: 5173,
        proxy: {
            "/api": {
                target: "http://django:8000",
                changeOrigin: true,
            },
            "/health": {
                target: "http://django:8000",
                changeOrigin: true,
            },
        },
    },
});
