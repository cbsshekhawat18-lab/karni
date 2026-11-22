import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import { karniGame } from "../../src/tooling/vite";

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, "../../src");

// A game project imports "@karni/game" from npm. The example builds against
// the package's source, so the tests check the code in this checkout.
export default defineConfig({
  root: here,
  plugins: [karniGame()],
  resolve: {
    alias: [
      { find: /^@karni\/game\/(collide|draw)$/, replacement: `${src}/$1/index.ts` },
      { find: /^@karni\/game$/, replacement: `${src}/index.ts` },
    ],
  },
  build: { outDir: "dist", emptyOutDir: true },
  logLevel: "warn",
});
