/** What a file in the manifest is, and so how it is loaded. */
export type AssetKind = "image" | "font" | "sound" | "data";

/** How a data file is read. Default by extension: ".json" is json, ".txt" and ".csv" text, else binary. */
export type DataFormat = "json" | "text" | "binary";

export interface AssetEntry {
  kind: AssetKind;
  /** Where the file is. Relative to the page, or an absolute URL on a host the build allows. */
  url: string;
  /** A WebP copy of an image, written by the build. Used where the browser decodes WebP. */
  webp?: string;
  /** What the player downloads, in bytes (the WebP copy when there is one). Gives exact progress. */
  bytes?: number;
  /** Font: the family name CSS uses. Default the entry's name. */
  family?: string;
  /** Font: CSS descriptors (`weight`, `style`). */
  weight?: string;
  style?: string;
  /** Data: how to read it. */
  format?: DataFormat;
}

export type AssetGroupEntries = Readonly<Record<string, AssetEntry>>;

/** Groups of named files. A group is the unit that loads and unloads (a stage's art). */
export interface AssetManifest {
  readonly groups: Readonly<Record<string, AssetGroupEntries>>;
}

/**
 * Write a manifest by hand and keep the exact group and file names for
 * the type checker. The Vite preset generates the same shape from the
 * `assets/` folder, so most games never call this.
 */
export function defineManifest<const M extends AssetManifest>(manifest: M): M {
  return manifest;
}

/** The group names of a manifest, as a type. */
export type GroupName<M extends AssetManifest> = Extract<keyof M["groups"], string>;
/** The file names of one group, as a type. */
export type AssetName<M extends AssetManifest, G extends GroupName<M>> = Extract<
  keyof M["groups"][G],
  string
>;
