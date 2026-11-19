import type { Plugin, UserConfig } from "vite";
import { resolvePortal, type PortalConfig } from "./config";
import { PORTALS, definePortals, portalRow, type PortalRow } from "./portals";

/** The module a game imports for its build's portal adapter. */
export const PORTAL_MODULE = "virtual:karni-game/portal";
const RESOLVED = `\0${PORTAL_MODULE}`;

export interface KarniGameViteOptions {
  /** The portal this build is for. Default `KARNI_GAME_PORTAL` from the environment, else "web". */
  portal?: string;
  /**
   * The portal while developing (`vite dev`). "fake" gives ads that play and
   * reward without any SDK. Default: the same as `portal`.
   */
  devPortal?: string;
  /** The portal table. Default Karni's (`PORTALS`); `definePortals` changes rows. */
  portals?: readonly PortalRow[];
  /** Portal ids and settings by portal. Values the environment can give instead. */
  config?: PortalConfig;
  /** Where `KARNI_GAME_*` values are read. Default `process.env`. */
  env?: Readonly<Record<string, string | undefined>>;
  /** Put the scripts and styles inside index.html, for file:// and sandboxed frames. */
  singleFile?: boolean;
  /** Keep the relative base (`./`) the portals and zips need. Default true. */
  relativeBase?: boolean;
}

function processEnv(): Readonly<Record<string, string | undefined>> {
  const scope = globalThis as unknown as { process?: { env?: Record<string, string | undefined> } };
  return scope.process?.env ?? {};
}

/** The source of the portal module for one portal and its options. */
export function portalModuleSource(
  row: Pick<PortalRow, "name" | "adapter">,
  options: object,
): string {
  const { module, factory } = row.adapter;
  return [
    `import { ${factory} } from ${JSON.stringify(module)};`,
    `export const portalName = ${JSON.stringify(row.name)};`,
    `export const portalOptions = ${JSON.stringify(options)};`,
    `export function createPortalAdapter() { return ${factory}(portalOptions); }`,
    `export default createPortalAdapter;`,
    "",
  ].join("\n");
}

const escapeScript = (code: string): string => code.replace(/<\/script/gi, "<\\/script");

/**
 * Inline the built scripts and styles into index.html. Exported for a
 * project's own pipeline; `singleFile: true` runs it.
 */
export function inlineIntoHtml(
  html: string,
  files: ReadonlyMap<string, { kind: "script" | "style"; code: string }>,
): { html: string; inlined: string[] } {
  const inlined: string[] = [];
  const find = (ref: string): { name: string; kind: "script" | "style"; code: string } | null => {
    const clean = ref.replace(/^\.?\//, "");
    const found = files.get(clean);
    return found ? { name: clean, ...found } : null;
  };
  let out = html.replace(
    /<script\b([^>]*)\bsrc="([^"]+)"([^>]*)><\/script>/g,
    (whole, before: string, src: string, after: string) => {
      const file = find(src);
      if (!file || file.kind !== "script") return whole;
      inlined.push(file.name);
      const module = /type="module"/.test(before + after) ? ' type="module"' : "";
      return `<script${module}>${escapeScript(file.code)}</script>`;
    },
  );
  out = out.replace(
    /<link\b[^>]*rel="stylesheet"[^>]*href="([^"]+)"[^>]*>/g,
    (whole, href: string) => {
      const file = find(href);
      if (!file || file.kind !== "style") return whole;
      inlined.push(file.name);
      return `<style>${file.code}</style>`;
    },
  );
  out = out.replace(/<link\b[^>]*rel="modulepreload"[^>]*>\s*/g, "");
  return { html: out, inlined };
}

/**
 * The Vite preset of a game: a relative base, the build's one portal adapter
 * behind `virtual:karni-game/portal`, that portal's SDK tag in the page, the
 * `__KARNI_GAME_DEV__` flag (true only in `vite dev`), and an optional
 * single-file build.
 */
export function karniGame(options: KarniGameViteOptions = {}): Plugin[] {
  const env = options.env ?? processEnv();
  const portals = options.portals ?? PORTALS;
  let command: "build" | "serve" = "build";
  let selected: { row: PortalRow; options: Record<string, unknown> } | null = null;

  const pick = (): { row: PortalRow; options: Record<string, unknown> } => {
    if (selected) return selected;
    const build = options.portal ?? env.KARNI_GAME_PORTAL ?? "web";
    const name = command === "serve" ? (options.devPortal ?? build) : build;
    if (name === "fake") {
      if (command !== "serve")
        throw new Error('The "fake" portal is for vite dev only, never a build');
      const rows = definePortals([
        {
          name: "fake",
          title: "Fake portal (development)",
          adapter: { module: "@karni/game/portals/fake", factory: "fakePortal" },
          zip: false,
        },
      ]);
      selected = { row: portalRow("fake", rows), options: { adMs: 1500 } };
    } else {
      selected = resolvePortal(name, { portals, config: options.config, env });
    }
    return selected;
  };

  const main: Plugin = {
    name: "karni-game",
    enforce: "pre",
    config(_config, environment): UserConfig {
      command = environment.command;
      const dev = environment.command === "serve";
      const config: UserConfig = {
        define: {
          __KARNI_GAME_DEV__: JSON.stringify(dev),
          __KARNI_GAME_PORTAL__: JSON.stringify(pick().row.name),
        },
      };
      if (options.relativeBase ?? true) config.base = "./";
      if (options.singleFile) {
        // Vite 8 bundles with Rolldown, earlier versions with Rollup: each has its own switch.
        const rolldown = "rolldownVersion" in this.meta;
        const output = rolldown ? { codeSplitting: false } : { inlineDynamicImports: true };
        config.build = {
          assetsInlineLimit: Number.MAX_SAFE_INTEGER,
          cssCodeSplit: false,
          modulePreload: false,
          [rolldown ? "rolldownOptions" : "rollupOptions"]: { output },
        } as UserConfig["build"];
      }
      return config;
    },
    resolveId(id) {
      return id === PORTAL_MODULE ? RESOLVED : null;
    },
    load(id) {
      if (id !== RESOLVED) return null;
      const { row, options: adapterOptions } = pick();
      return portalModuleSource(row, adapterOptions);
    },
    transformIndexHtml() {
      const { row } = pick();
      return row.headScript
        ? [{ tag: "script", attrs: { src: row.headScript }, injectTo: "head-prepend" }]
        : [];
    },
  };

  const singleFile: Plugin = {
    name: "karni-game:single-file",
    apply: "build",
    enforce: "post",
    generateBundle(_output, bundle) {
      const page = bundle["index.html"];
      if (!page || page.type !== "asset") return;
      const files = new Map<string, { kind: "script" | "style"; code: string }>();
      for (const [name, file] of Object.entries(bundle)) {
        if (file.type === "chunk") files.set(name, { kind: "script", code: file.code });
        else if (name.endsWith(".css"))
          files.set(name, { kind: "style", code: String(file.source) });
      }
      const { html, inlined } = inlineIntoHtml(String(page.source), files);
      page.source = html;
      for (const name of inlined) {
        Reflect.deleteProperty(bundle, name);
        Reflect.deleteProperty(bundle, `${name}.map`);
      }
    },
  };

  return options.singleFile ? [main, singleFile] : [main];
}

export default karniGame;
