// The portal build of the game: frontend/portal on its own, one package per portal.
// From frontend/: npm run game:package (karni-game package --root portal), which
// sets the portal (KARNI_GAME_PORTAL) of each build. KARNI_GAME_API_URL names the
// game API the packages call. To play it in a browser: npx vite portal.
import { karniGame } from "@karni/game/vite";
import { defineConfig } from "vite";

export default defineConfig({
    plugins: [karniGame()],
    build: { outDir: "dist", emptyOutDir: true, target: "es2022" },
});
