import type { Plugin, UserConfig } from "vite";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, isAbsolute, join, resolve as resolvePath } from "node:path";
import {
  ASSET_DIR,
  ASSET_REPORT,
  manifestSource,
  reportOf,
  scanAssets,
  sharpEncoder,
  typesSource,
  type GroupBudget,
  type ScannedAsset,
  type WebpEncoder,
} from "./assets";
import { apiHosts, resolveApiUrl, resolvePortal, type PortalConfig } from "./config";
import { PORTALS, definePortals, portalRow, type PortalRow } from "./portals";

/** The module a game imports for its asset manifest. */
export const ASSETS_MODULE = "virtual:karni-game/assets";
const ASSETS_RESOLVED = `\0${ASSETS_MODULE}`;

/** The module a game imports for its build's portal adapter. */
export const PORTAL_MODULE = "virtual:karni-game/portal";
const RESOLVED = `\0${PORTAL_MODULE}`;

export interface AssetsPluginOptions {
  /** The folder of the game's files, from the project root. Default "assets". */
  dir?: string;
  /**
   * The most one group may download, in bytes: one number for every group,
   * or a table by group name (`"*"` for the rest). Default 2 MiB. The package
   * check fails a group over it.
   */
  budget?: GroupBudget;
  /**
   * Write a WebP copy of each PNG and JPEG when it is smaller, and keep the
   * original as the fallback. `false` keeps the originals. Default true in a build.
   * `encode` is the encoder to use (default: `sharp`, if the project installed it).
   */
  webp?: boolean | { quality?: number; encode?: WebpEncoder };
  /** Write a `.d.ts` with the exact group and file names, at this path from the root. */
  types?: string;
  /** Hosts files may be fetched from besides the portal's own and the game API's. Default none. */
  hosts?: readonly string[];
}

export interface KarniGameViteOptions {
  /**
   * The asset manifest: `virtual:karni-game/assets` lists the files of the
   * assets folder by group. On when the folder exists. `false` turns it off.
   */
  assets?: AssetsPluginOptions | false;
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
  /**
   * The game API a build calls from another origin (a portal's), as
   * `https://api.example.com`: `gameApiUrl` of `virtual:karni-game/portal`.
   * Default `KARNI_GAME_API_URL`, else null: the page's own origin.
   */
  apiUrl?: string;
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
  apiUrl: string | null = null,
): string {
  const { module, factory } = row.adapter;
  return [
    `import { ${factory} } from ${JSON.stringify(module)};`,
    `export const portalName = ${JSON.stringify(row.name)};`,
    `export const portalOptions = ${JSON.stringify(options)};`,
    `export const gameApiUrl = ${JSON.stringify(apiUrl)};`,
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

function assetsPlugin(
  options: KarniGameViteOptions,
  pick: () => { row: PortalRow },
  apiUrl: string | null,
): Plugin {
  const settings: AssetsPluginOptions = options.assets || {};
  let root = process.cwd();
  let building = false;
  let scanned: ScannedAsset[] | null = null;

  const dir = (): string => {
    const folder = settings.dir ?? ASSET_DIR;
    return isAbsolute(folder) ? folder : resolvePath(root, folder);
  };
  const scan = async (): Promise<ScannedAsset[]> => {
    const webp = settings.webp ?? true;
    const given = typeof webp === "object" ? webp.encode : undefined;
    const quality = typeof webp === "object" ? (webp.quality ?? 80) : 80;
    const encode = webp && building ? (given ?? (await sharpEncoder(quality))) : null;
    if (webp && building && !encode) {
      console.warn(
        "karni-game: no WebP copies were made. Install `sharp` (npm i -D sharp) or pass assets.webp.encode.",
      );
    }
    scanned = await scanAssets(dir(), {
      encode,
      cacheDir: join(root, "node_modules", ".cache", "karni-game", "webp"),
    });
    return scanned;
  };

  return {
    name: "karni-game:assets",
    enforce: "pre",
    configResolved(config) {
      root = config.root;
      building = config.command === "build";
    },
    resolveId(id) {
      return id === ASSETS_MODULE ? ASSETS_RESOLVED : null;
    },
    async buildStart() {
      if (options.assets === false || !existsSync(dir())) return;
      this.addWatchFile(dir());
      const assets = await scan();
      if (settings.types) {
        const file = resolvePath(root, settings.types);
        const text = typesSource(assets);
        const same = existsSync(file) && readFileSync(file, "utf8") === text;
        if (!same) {
          mkdirSync(dirname(file), { recursive: true });
          writeFileSync(file, text);
        }
      }
    },
    async load(id) {
      if (id !== ASSETS_RESOLVED) return null;
      const assets = options.assets === false ? [] : (scanned ?? (await scan()));
      const hosts = [...pick().row.hosts, ...apiHosts(apiUrl), ...(settings.hosts ?? [])];
      return manifestSource(assets, hosts, settings.budget);
    },
    generateBundle() {
      if (options.assets === false || !scanned || scanned.length === 0) return;
      this.emitFile({
        type: "asset",
        fileName: ASSET_REPORT,
        source: JSON.stringify(reportOf(scanned, settings.budget), null, 2),
      });
    },
  };
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
  const apiUrl = resolveApiUrl(options.apiUrl, env);
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
      return portalModuleSource(row, adapterOptions, apiUrl);
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

  const plugins = [
    main,
    assetsPlugin(options, pick, apiUrl),
    ...(options.singleFile ? [singleFile] : []),
  ];
  return plugins;
}

export default karniGame;
