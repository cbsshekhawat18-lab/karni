import { existsSync, mkdirSync, rmSync, statSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { checkPackage, type BuildProblem, type CheckOptions } from "./checks";
import { API_URL_ENV, apiHosts, resolveApiUrl } from "./config";
import { PORTALS, portalRow, type PortalRow } from "./portals";
import { zipFolder } from "./zip";

export interface PackageOptions {
  /** The game's project folder (where its vite.config is). Default the working folder. */
  root?: string;
  /** The portals to build. Default every row of the table. */
  portals?: readonly string[];
  /** The portal table. Default Karni's. */
  table?: readonly PortalRow[];
  /** Where each package lands, as `<outDir>/<portal>/` (and `<portal>.zip`). Default "dist-portals". */
  outDir?: string;
  /** Build one portal into a folder. Default: `vite build` with `KARNI_GAME_PORTAL` set. */
  build?: (portal: string, outDir: string, root: string) => Promise<void>;
  check?: CheckOptions;
  /**
   * The game API the packages call (`https://api.example.com`): each build
   * gets it as `KARNI_GAME_API_URL`, and the checks allow its host. Default
   * `KARNI_GAME_API_URL` from the environment.
   */
  apiUrl?: string;
}

export interface PackageReport {
  portal: string;
  dir: string;
  zip: string | null;
  bytes: number;
  problems: BuildProblem[];
}

function size(dir: string): number {
  let total = 0;
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    total += statSync(path).isDirectory() ? size(path) : statSync(path).size;
  }
  return total;
}

/** Build with the project's own Vite config, for one portal. */
export async function viteBuild(portal: string, outDir: string, root: string): Promise<void> {
  const vite = await import("vite");
  const scope = globalThis as unknown as { process: { env: Record<string, string | undefined> } };
  const before = scope.process.env.KARNI_GAME_PORTAL;
  scope.process.env.KARNI_GAME_PORTAL = portal;
  try {
    await vite.build({ root, logLevel: "warn", build: { outDir, emptyOutDir: true } });
  } finally {
    if (before === undefined) delete scope.process.env.KARNI_GAME_PORTAL;
    else scope.process.env.KARNI_GAME_PORTAL = before;
  }
}

/**
 * The per-portal packaging step: one build per portal (each with its own
 * SDK and no other), every package checked, and zipped when its row says.
 * Returns a report per portal; any problem is listed there and a package
 * with problems is not zipped.
 */
export async function packagePortals(options: PackageOptions = {}): Promise<PackageReport[]> {
  const root = resolve(options.root ?? ".");
  const table = options.table ?? PORTALS;
  const names = options.portals ?? table.map((row) => row.name);
  const outDir = resolve(root, options.outDir ?? "dist-portals");
  const build = options.build ?? viteBuild;
  const env = (globalThis as unknown as { process: { env: Record<string, string | undefined> } })
    .process.env;
  const apiUrl = resolveApiUrl(options.apiUrl, env);
  const check: CheckOptions = {
    ...options.check,
    allowHosts: [...(options.check?.allowHosts ?? []), ...apiHosts(apiUrl)],
  };
  const before = env[API_URL_ENV];
  if (apiUrl) env[API_URL_ENV] = apiUrl;
  mkdirSync(outDir, { recursive: true });
  try {
    return await packageEach(names, { root, table, outDir, build, check });
  } finally {
    if (before === undefined) Reflect.deleteProperty(env, API_URL_ENV);
    else env[API_URL_ENV] = before;
  }
}

async function packageEach(
  names: readonly string[],
  options: {
    root: string;
    table: readonly PortalRow[];
    outDir: string;
    build: (portal: string, outDir: string, root: string) => Promise<void>;
    check: CheckOptions;
  },
): Promise<PackageReport[]> {
  const { root, table, outDir, build } = options;
  const reports: PackageReport[] = [];
  for (const name of names) {
    const row = portalRow(name, table);
    const dir = join(outDir, row.name);
    const zipPath = join(outDir, `${row.name}.zip`);
    rmSync(zipPath, { force: true });
    await build(row.name, dir, root);
    const problems = checkPackage(dir, row, { portals: table, ...options.check });
    let zip: string | null = null;
    if (row.zip && problems.length === 0 && existsSync(dir)) {
      zipFolder(dir, zipPath);
      zip = zipPath;
    }
    reports.push({ portal: row.name, dir, zip, bytes: existsSync(dir) ? size(dir) : 0, problems });
  }
  return reports;
}
