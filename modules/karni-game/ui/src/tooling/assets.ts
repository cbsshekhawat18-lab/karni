import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { basename, extname, join, relative, sep } from "node:path";
import type { AssetKind } from "../assets/manifest";
import type { BuildProblem } from "./checks";

/** The folder the preset reads, under the project's root. */
export const ASSET_DIR = "assets";
/** The group of files that sit directly in the folder, outside any group's own. */
export const CORE_GROUP = "core";
/** The largest download of one group when the project sets none: 2 MiB. */
export const DEFAULT_GROUP_BUDGET = 2 * 1024 * 1024;
/** The report the build writes into the package, which the package check reads. */
export const ASSET_REPORT = "karni-assets.json";

const KINDS: Record<string, AssetKind> = {
  ".png": "image",
  ".jpg": "image",
  ".jpeg": "image",
  ".gif": "image",
  ".webp": "image",
  ".avif": "image",
  ".svg": "image",
  ".woff2": "font",
  ".woff": "font",
  ".ttf": "font",
  ".otf": "font",
  ".ogg": "sound",
  ".mp3": "sound",
  ".wav": "sound",
  ".m4a": "sound",
  ".opus": "sound",
  ".json": "data",
  ".txt": "data",
  ".csv": "data",
  ".tsv": "data",
  ".bin": "data",
};
/** Formats a WebP copy is made of: still pictures a lossy copy suits. */
const WEBP_SOURCES = new Set([".png", ".jpg", ".jpeg"]);

/** What kind of asset a file is by its extension, or null for a file the manifest leaves out. */
export function kindOfFile(path: string): AssetKind | null {
  return KINDS[extname(path).toLowerCase()] ?? null;
}

/** Turns picture bytes into WebP bytes. */
export type WebpEncoder = (input: Uint8Array, file: string) => Promise<Uint8Array>;

/**
 * The encoder the build uses when none is given: the `sharp` package, loaded
 * only if the project installed it. Null when it is not there, and the build
 * then keeps the originals (and says so).
 */
export async function sharpEncoder(quality = 80): Promise<WebpEncoder | null> {
  try {
    const name = "sharp";
    const module = (await import(/* @vite-ignore */ name)) as {
      default: (input: Uint8Array) => {
        webp(options: { quality: number }): { toBuffer(): Promise<Uint8Array> };
      };
    };
    return (input) => module.default(input).webp({ quality }).toBuffer();
  } catch {
    return null;
  }
}

export interface ScannedAsset {
  group: string;
  /** The name a game uses: the path inside the group, no extension, `/` between folders. */
  name: string;
  /** The file on disk. */
  file: string;
  kind: AssetKind;
  /** Bytes of the original. */
  originalBytes: number;
  /** A WebP copy on disk, smaller than the original. */
  webp?: { file: string; bytes: number };
  /** What the player downloads: the copy when there is one. */
  bytes: number;
}

function walk(dir: string): string[] {
  const files: string[] = [];
  for (const entry of readdirSync(dir).sort()) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) files.push(...walk(path));
    else files.push(path);
  }
  return files;
}

export interface ScanOptions {
  /** Where WebP copies are written. Default none: no copies. */
  cacheDir?: string;
  encode?: WebpEncoder | null;
  /** Skip files the manifest has no kind for. Default true (a README beside the art is fine). */
  quiet?: boolean;
}

/**
 * Read an assets folder into a list of files by group. A group is a folder
 * of the first level and a file at the first level is in `core`. Two files
 * that would get one name (`hero.png` and `hero.jpg`) stop the build.
 */
export async function scanAssets(dir: string, options: ScanOptions = {}): Promise<ScannedAsset[]> {
  if (!existsSync(dir)) return [];
  const found: ScannedAsset[] = [];
  const names = new Map<string, string>();
  for (const file of walk(dir)) {
    const kind = kindOfFile(file);
    if (!kind) continue;
    const parts = relative(dir, file).split(sep);
    const group = parts.length > 1 ? (parts[0] as string) : CORE_GROUP;
    const inside = parts.length > 1 ? parts.slice(1) : parts;
    const last = inside[inside.length - 1] as string;
    inside[inside.length - 1] = last.slice(0, last.length - extname(last).length);
    const name = inside.join("/");
    const key = `${group}/${name}`;
    const other = names.get(key);
    if (other) {
      throw new Error(
        `Karni assets: ${relative(dir, file)} and ${relative(dir, other)} would both be "${key}": rename one`,
      );
    }
    names.set(key, file);
    const originalBytes = statSync(file).size;
    const asset: ScannedAsset = { group, name, file, kind, originalBytes, bytes: originalBytes };
    if (
      kind === "image" &&
      options.encode &&
      options.cacheDir &&
      WEBP_SOURCES.has(extname(file).toLowerCase())
    ) {
      const input = readFileSync(file);
      const hash = createHash("sha1")
        .update(input)
        .update(String(options.encode))
        .digest("hex")
        .slice(0, 20);
      const copy = join(options.cacheDir, `${basename(file, extname(file))}-${hash}.webp`);
      let size = existsSync(copy) ? statSync(copy).size : 0;
      if (size === 0) {
        const out = await options.encode(input, file);
        mkdirSync(options.cacheDir, { recursive: true });
        writeFileSync(copy, out);
        size = out.byteLength;
      }
      // A copy that is not smaller is no use to anyone.
      if (size < originalBytes) {
        asset.webp = { file: copy, bytes: size };
        asset.bytes = size;
      }
    }
    found.push(asset);
  }
  return found;
}

export type GroupBudget = number | Readonly<Record<string, number>>;

export function budgetOf(budget: GroupBudget | undefined, group: string): number {
  if (typeof budget === "number") return budget;
  return budget?.[group] ?? budget?.["*"] ?? DEFAULT_GROUP_BUDGET;
}

/** What the build knows of each group, written to the package as `karni-assets.json`. */
export interface AssetReport {
  version: 1;
  groups: Record<string, { files: number; bytes: number; originalBytes: number; budget: number }>;
}

export function reportOf(assets: readonly ScannedAsset[], budget?: GroupBudget): AssetReport {
  const groups: AssetReport["groups"] = {};
  for (const asset of assets) {
    const group = (groups[asset.group] ??= {
      files: 0,
      bytes: 0,
      originalBytes: 0,
      budget: budgetOf(budget, asset.group),
    });
    group.files += 1;
    group.bytes += asset.bytes;
    group.originalBytes += asset.originalBytes;
  }
  return { version: 1, groups };
}

/** One problem for each group that downloads more than its budget. */
export function checkAssetReport(report: AssetReport): BuildProblem[] {
  return Object.entries(report.groups)
    .filter(([, group]) => group.bytes > group.budget)
    .map(([name, group]) => ({
      rule: "asset-budget",
      file: ASSET_REPORT,
      message: `the asset group "${name}" is ${group.bytes} bytes (${group.files} files), over its budget of ${group.budget}: split it into groups that load when needed, or shrink the files`,
    }));
}

/** The text of `virtual:karni-game/assets`: the manifest, with each file imported so the bundler hashes it. */
export function manifestSource(
  assets: readonly ScannedAsset[],
  hosts: readonly string[],
  budget?: GroupBudget,
): string {
  const lines: string[] = [];
  let n = 0;
  const imp = (file: string): string => {
    const id = `f${(n += 1)}`;
    lines.push(`import ${id} from ${JSON.stringify(`${file}?url`)};`);
    return id;
  };
  const groups = new Map<string, string[]>();
  for (const asset of assets) {
    const fields = [`kind: ${JSON.stringify(asset.kind)}`, `url: ${imp(asset.file)}`];
    if (asset.webp) fields.push(`webp: ${imp(asset.webp.file)}`);
    fields.push(`bytes: ${asset.bytes}`);
    if (asset.kind === "data") {
      // Written down so an inlined file (a data: URL has no extension) is read the same way.
      const ext = asset.file.toLowerCase().split(".").pop() ?? "";
      const format =
        ext === "json" ? "json" : ["txt", "csv", "tsv"].includes(ext) ? "text" : "binary";
      fields.push(`format: ${JSON.stringify(format)}`);
    }
    if (asset.kind === "font")
      fields.push(`family: ${JSON.stringify(asset.name.split("/").pop())}`);
    (groups.get(asset.group) ?? groups.set(asset.group, []).get(asset.group) ?? []).push(
      `${JSON.stringify(asset.name)}: { ${fields.join(", ")} }`,
    );
  }
  const body = [...groups].map(
    ([group, entries]) => `${JSON.stringify(group)}: { ${entries.join(", ")} }`,
  );
  return [
    ...lines,
    `export const manifest = { groups: { ${body.join(", ")} } };`,
    `export const assetHosts = ${JSON.stringify(hosts)};`,
    `export const assetBudgets = ${JSON.stringify(
      Object.fromEntries([...groups.keys()].map((group) => [group, budgetOf(budget, group)])),
    )};`,
    "",
  ].join("\n");
}

/** A `.d.ts` that gives `virtual:karni-game/assets` the exact group and file names. */
export function typesSource(assets: readonly ScannedAsset[]): string {
  const groups = new Map<string, string[]>();
  for (const asset of assets) {
    (groups.get(asset.group) ?? groups.set(asset.group, []).get(asset.group) ?? []).push(
      `${JSON.stringify(asset.name)}: AssetEntry;`,
    );
  }
  const body = [...groups].map(
    ([group, names]) =>
      `  readonly ${JSON.stringify(group)}: { ${names.map((n) => `readonly ${n}`).join(" ")} };`,
  );
  return [
    "// Written by the karniGame() Vite preset from the assets folder. Do not edit.",
    'import type { AssetEntry } from "@karni/game/assets";',
    "",
    "declare global {",
    "  interface KarniAssetGroups {",
    ...body.map((line) => `  ${line}`),
    "  }",
    "}",
    "export {};",
    "",
  ].join("\n");
}
