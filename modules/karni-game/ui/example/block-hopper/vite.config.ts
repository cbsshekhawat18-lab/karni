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
  plugins: [karniGame({ devPortal: "fake", singleFile: process.env.BLOCK_HOPPER_SINGLE === "1" })],
  resolve: {
    alias: [
      { find: /^@karni\/game\/portals\/(.*)$/, replacement: `${src}/portal/adapters/$1.ts` },
      { find: /^@karni\/game\/scenes$/, replacement: `${src}/scenes/index.ts` },
      { find: /^@karni\/game\/sim$/, replacement: `${src}/sim/index.ts` },
      { find: /^@karni\/game\/ui$/, replacement: `${src}/ui/index.ts` },
      { find: /^@karni\/game$/, replacement: `${src}/index.ts` },
    ],
  },
  build: { outDir: "dist", emptyOutDir: true },
  logLevel: "warn",
});
