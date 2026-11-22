import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, "../../../src");

/** The benchmark page, built against the package's source like the examples. */
export default defineConfig({
  root: here,
  base: "./",
  resolve: {
    alias: [
      { find: /^@karni\/game\/(collide|draw)$/, replacement: `${src}/$1/index.ts` },
      { find: /^@karni\/game$/, replacement: `${src}/index.ts` },
    ],
  },
  build: { outDir: "dist", emptyOutDir: true },
  logLevel: "warn",
});
