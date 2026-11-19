import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import { karniGame } from "../../../src/tooling/vite";

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, "../../../src");

// The test builds against the package's source, as a project builds against the installed package.
export default defineConfig({
  plugins: [karniGame({ singleFile: process.env.TINY_SINGLE === "1" })],
  resolve: {
    alias: [
      { find: /^@karni\/game\/portals\/(.*)$/, replacement: `${src}/portal/adapters/$1.ts` },
      { find: /^@karni\/game$/, replacement: `${src}/index.ts` },
    ],
  },
  logLevel: "warn",
});
