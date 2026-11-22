// The game's Vite config. `npm run dev` serves it at /play/__GAME_SLUG__/, the path the
// project serves the build at (http://localhost:5174/play/__GAME_SLUG__/), and proxies
// the game API to Django: KARNI_API_PROXY when it is set (docker compose sets
// http://django:8000 for its container), else runserver on 127.0.0.1 at KARNI_DEV_PORT
// (default 8000), both read from the environment or the project's .env.
// `npm run build` writes dist/ with a relative base: the project serves it at
// /play/__GAME_SLUG__/, and `npm run package` builds the same game for each portal.
import { fileURLToPath } from "node:url";
import { karniGame } from "@karni/game/vite";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
    const env = loadEnv(mode, fileURLToPath(new URL("../..", import.meta.url)), "KARNI_");
    const target = env.KARNI_API_PROXY || `http://127.0.0.1:${env.KARNI_DEV_PORT || "8000"}`;
    const proxy = { "/api": { target, changeOrigin: true } };
    return {
        // No assets/ folder: every picture is drawn in code and every sound is made by sfx.
        plugins: [karniGame({ devBase: "/play/__GAME_SLUG__/", devPortal: "fake", assets: false })],
        server: { host: true, port: 5174, proxy },
        preview: { host: true, port: 4174, proxy },
        build: { outDir: "dist", emptyOutDir: true, target: "es2022" },
    };
});
