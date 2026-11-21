import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import dts from "vite-plugin-dts";

const root = dirname(fileURLToPath(import.meta.url));

/**
 * Every published entry point: the key is the file under dist/ (without .js),
 * the value the source it is built from. package.json "exports" maps onto it.
 */
const ENTRIES: Record<string, string> = {
  index: "src/index.ts",
  "portals/none": "src/portal/adapters/none.ts",
  "portals/fake": "src/portal/adapters/fake.ts",
  "portals/poki": "src/portal/adapters/poki.ts",
  "portals/crazygames": "src/portal/adapters/crazygames.ts",
  "portals/gamedistribution": "src/portal/adapters/gamedistribution.ts",
  "portals/y8": "src/portal/adapters/y8.ts",
  build: "src/tooling/index.ts",
  vite: "src/tooling/vite.ts",
  cli: "src/tooling/cli.ts",
  phaser: "src/engines/phaser.ts",
  pixi: "src/engines/pixi.ts",
  r3f: "src/engines/r3f.tsx",
  smoke: "src/smoke/index.ts",
  collide: "src/collide/index.ts",
  draw: "src/draw/index.ts",
};

export default defineConfig({
  plugins: [
    dts({
      entryRoot: ".",
      include: ["src"],
      exclude: ["**/*.test.*", "tests/**", "dist/**"],
      tsconfigPath: resolve(root, "tsconfig.json"),
    }),
  ],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: true,
    target: "es2022",
    minify: false,
    lib: {
      entry: Object.fromEntries(
        Object.entries(ENTRIES).map(([name, source]) => [name, resolve(root, source)]),
      ),
      // ESM only: every entry is tree-shaken by the game's bundler.
      formats: ["es"],
      fileName: (_format, entryName) => `${entryName}.js`,
    },
    rollupOptions: {
      // Externalize every bare import and Node builtin: optional peers (vite,
      // playwright, phaser, pixi.js, react) are resolved by the consumer.
      external: (id) => !id.startsWith(".") && !id.startsWith("/") && !id.startsWith("\0"),
      output: { exports: "named" },
    },
  },
});
