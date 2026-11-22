import type { GameAudio } from "../audio";
import {
  AssetLoadError,
  browserPlatform,
  formatOf,
  type AssetFailure,
  type ImageSource,
  type Platform,
} from "./loader";
import type { AssetEntry, AssetManifest, AssetName, GroupName } from "./manifest";

export interface AssetsOptions<M extends AssetManifest> {
  manifest: M;
  /** Needed for sounds: decoded on its context. */
  audio?: Pick<GameAudio, "decode">;
  /**
   * Hosts a file may come from besides the page's own origin. Default none:
   * a file on any other host is refused, so a portal build never fetches from a
   * host it does not allow. The preset's `assetHosts` is the build's list.
   */
  allowHosts?: readonly string[];
  /** Tries after the first one for each file. Default 2. */
  retries?: number;
  /** Wait before try `n` (1 for the first retry), in ms. Default 250, 500, 1000... */
  retryDelay?(attempt: number): number;
  /** Give up on one try after this many ms. Default 20000. */
  timeout?: number;
  /** Files loaded at once. Default 6. */
  concurrency?: number;
  /** Use the WebP copy where the browser decodes it. Default true. */
  webp?: boolean;
  /** The browser pieces, to replace one (a test, an engine's own decoder). */
  platform?: Partial<Platform>;
}

/** Where a load is. `fraction` goes from 0 to 1 and never goes back. */
export interface LoadProgress {
  group: string;
  loaded: number;
  total: number;
  /** Bytes of the files done, and of the group, when the manifest knows them. */
  bytesLoaded: number;
  bytesTotal: number;
  fraction: number;
}

export interface LoadOptions {
  onProgress?(progress: LoadProgress): void;
  /**
   * Throw an `AssetLoadError` when a file fails after its retries (the default).
   * `false` resolves with the failures listed instead, and the game goes on.
   */
  strict?: boolean;
  signal?: AbortSignal;
}

export interface LoadReport {
  group: string;
  loaded: number;
  failed: readonly AssetFailure[];
}

/** A decoded image: pass `source` to `drawImage`. */
export interface ImageAsset {
  readonly source: CanvasImageSource;
  readonly width: number;
  readonly height: number;
}

type Held =
  | { kind: "image"; image: ImageSource; memory: number }
  | { kind: "font"; handle: unknown; memory: number }
  | { kind: "sound"; buffer: AudioBuffer; memory: number }
  | { kind: "data"; value: unknown; memory: number };

export interface Assets<M extends AssetManifest> {
  readonly manifest: M;
  /** Fetch and decode every file of a group. A second call while loading shares the first. */
  load<G extends GroupName<M>>(group: G, options?: LoadOptions): Promise<LoadReport>;
  /** Free a group: bitmaps closed, fonts removed, buffers dropped. Returns the bytes of memory freed. */
  unload<G extends GroupName<M>>(group: G): number;
  isLoaded<G extends GroupName<M>>(group: G): boolean;
  /** An estimate of the memory a loaded group holds, in bytes. */
  memory<G extends GroupName<M>>(group: G): number;
  /** The download size of a group in bytes (0 when the manifest has no sizes). */
  size<G extends GroupName<M>>(group: G): number;
  image<G extends GroupName<M>>(group: G, name: AssetName<M, G>): ImageAsset;
  sound<G extends GroupName<M>>(group: G, name: AssetName<M, G>): AudioBuffer;
  /** A data file: parsed JSON, text (for .txt and .csv) or an ArrayBuffer. Typed `unknown`: check it before use. */
  data<G extends GroupName<M>>(group: G, name: AssetName<M, G>): unknown;
  /** Resolves once every font of the groups loaded so far is usable, so the first text draws in it. */
  fontsReady(): Promise<void>;
}

const CONTENT_ERROR = "Karni assets: ";

/** The page's own: a relative URL, `data:`, `blob:`, a file next to a `file://` page, or this page's origin. */
function ownUrl(url: string): boolean {
  let parsed: URL;
  try {
    parsed = new URL(url, "relative:///");
  } catch {
    return false;
  }
  if (parsed.protocol === "relative:") return true;
  if (["data:", "blob:", "file:"].includes(parsed.protocol)) return true;
  const here = (globalThis as { location?: { origin?: string } }).location?.origin;
  return here !== undefined && parsed.origin === here;
}

/**
 * Load a manifest's groups with progress, retries and a readable failure, and
 * free them again. Images decode off the main thread where the browser allows,
 * fonts are added before the load resolves, and no file is fetched from a host
 * that was not allowed.
 */
export function createAssets<M extends AssetManifest>(options: AssetsOptions<M>): Assets<M> {
  const platform: Platform = { ...browserPlatform(), ...options.platform };
  const manifest = options.manifest;
  const retries = Math.max(0, options.retries ?? 2);
  const delay = options.retryDelay ?? ((attempt: number) => 250 * 2 ** (attempt - 1));
  const timeout = options.timeout ?? 20_000;
  const concurrency = Math.max(1, options.concurrency ?? 6);
  const allowed = new Set((options.allowHosts ?? []).map((host) => host.toLowerCase()));
  const held = new Map<string, Map<string, Held>>();
  const loading = new Map<string, Promise<LoadReport>>();
  const fontLoads = new Set<Promise<unknown>>();

  const entriesOf = (group: string): [string, AssetEntry][] => {
    const entries = manifest.groups[group];
    if (!entries) {
      const names = Object.keys(manifest.groups).join(", ") || "none";
      throw new Error(`${CONTENT_ERROR}no group "${group}" in the manifest (groups: ${names})`);
    }
    return Object.entries(entries);
  };

  const check = (url: string): void => {
    if (ownUrl(url)) return;
    let host: string | null = null;
    try {
      host = new URL(url).hostname.toLowerCase();
    } catch {
      // A URL that does not parse is refused below.
    }
    if (!host || !allowed.has(host)) {
      throw new Error(`${host ?? url} is not an allowed host (allowHosts)`);
    }
  };

  const fetchOnce = async (url: string, outer?: AbortSignal): Promise<Response> => {
    check(url);
    const controller = new AbortController();
    const abort = (): void => controller.abort();
    outer?.addEventListener("abort", abort);
    const timer = setTimeout(abort, timeout);
    try {
      const response = await platform.fetch(url, { signal: controller.signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response;
    } catch (error) {
      if (controller.signal.aborted && !outer?.aborted) throw new Error("timed out");
      throw error;
    } finally {
      clearTimeout(timer);
      outer?.removeEventListener("abort", abort);
    }
  };

  const loadOne = async (
    name: string,
    entry: AssetEntry,
    signal: AbortSignal | undefined,
  ): Promise<Held> => {
    // The WebP copy is tried once. The original has the retries, so a bad copy costs one fetch.
    if (entry.kind === "image" && entry.webp && (options.webp ?? true) && (await platform.webp())) {
      try {
        return await decode(name, entry, entry.webp, signal);
      } catch {
        if (signal?.aborted) throw new Error("cancelled");
      }
    }
    let last: unknown;
    for (let attempt = 0; attempt <= retries; attempt += 1) {
      if (attempt > 0) await platform.wait(delay(attempt));
      if (signal?.aborted) throw new Error("cancelled");
      try {
        return await decode(name, entry, entry.url, signal);
      } catch (error) {
        last = error;
      }
    }
    throw last instanceof Error ? last : new Error(String(last));
  };

  const decode = async (
    name: string,
    entry: AssetEntry,
    url: string,
    signal: AbortSignal | undefined,
  ): Promise<Held> => {
    const response = await fetchOnce(url, signal);
    if (entry.kind === "image") {
      const image = await platform.decodeImage(await response.blob());
      return { kind: "image", image, memory: image.width * image.height * 4 };
    }
    if (entry.kind === "font") {
      const data = await response.arrayBuffer();
      const family = entry.family ?? name;
      const handle = await platform.addFont(family, data, {
        ...(entry.weight ? { weight: entry.weight } : {}),
        ...(entry.style ? { style: entry.style } : {}),
      });
      return { kind: "font", handle, memory: data.byteLength };
    }
    if (entry.kind === "sound") {
      if (!options.audio) throw new Error("createAssets needs `audio` to load sounds");
      const buffer = await options.audio.decode(await response.arrayBuffer());
      if (!buffer) throw new Error("the browser could not decode it");
      return {
        kind: "sound",
        buffer,
        memory: buffer.length * buffer.numberOfChannels * 4,
      };
    }
    const format = formatOf(entry);
    if (format === "json") {
      const text = await response.text();
      return { kind: "data", value: JSON.parse(text) as unknown, memory: text.length * 2 };
    }
    if (format === "text") {
      const text = await response.text();
      return { kind: "data", value: text, memory: text.length * 2 };
    }
    const data = await response.arrayBuffer();
    return { kind: "data", value: data, memory: data.byteLength };
  };

  const run = async (group: string, load: LoadOptions): Promise<LoadReport> => {
    const entries = entriesOf(group);
    const files = new Map<string, Held>();
    const failures: AssetFailure[] = [];
    const bytesTotal = entries.reduce((sum, [, entry]) => sum + (entry.bytes ?? 0), 0);
    const exact = entries.every(([, entry]) => entry.bytes !== undefined) && bytesTotal > 0;
    let done = 0;
    let bytesDone = 0;
    let shown = 0;
    const report = (): void => {
      const raw = exact ? bytesDone / bytesTotal : entries.length ? done / entries.length : 1;
      shown = Math.max(shown, Math.min(1, raw));
      load.onProgress?.({
        group,
        loaded: done,
        total: entries.length,
        bytesLoaded: bytesDone,
        bytesTotal,
        fraction: done === entries.length ? 1 : shown,
      });
    };
    report();
    const queue = [...entries];
    const worker = async (): Promise<void> => {
      for (let next = queue.shift(); next; next = queue.shift()) {
        const [name, entry] = next;
        try {
          files.set(name, await loadOne(name, entry, load.signal));
        } catch (error) {
          failures.push({
            group,
            name,
            url: entry.url,
            reason: error instanceof Error ? error.message : String(error),
          });
        }
        done += 1;
        bytesDone += entry.bytes ?? 0;
        report();
      }
    };
    const workers = Promise.all(
      Array.from({ length: Math.min(concurrency, entries.length) }, worker),
    );
    fontLoads.add(workers);
    try {
      await workers;
    } finally {
      fontLoads.delete(workers);
    }
    if (load.signal?.aborted) {
      free(files);
      throw new Error(`${CONTENT_ERROR}loading "${group}" was cancelled`);
    }
    if (failures.length > 0 && (load.strict ?? true)) {
      free(files);
      throw new AssetLoadError(group, failures);
    }
    held.set(group, files);
    return { group, loaded: files.size, failed: failures };
  };

  const free = (files: Map<string, Held>): number => {
    let memory = 0;
    for (const file of files.values()) {
      memory += file.memory;
      if (file.kind === "image") file.image.close();
      else if (file.kind === "font") platform.removeFont(file.handle);
    }
    files.clear();
    return memory;
  };

  const get = <K extends Held["kind"]>(
    group: string,
    name: string,
    kind: K,
  ): Extract<Held, { kind: K }> => {
    const files = held.get(group);
    if (!files) {
      throw new Error(
        `${CONTENT_ERROR}group "${group}" is not loaded: call load("${group}") first`,
      );
    }
    const file = files.get(name);
    if (!file) {
      const names = [...files.keys()].join(", ") || "none";
      throw new Error(`${CONTENT_ERROR}no file "${name}" in "${group}" (files: ${names})`);
    }
    if (file.kind !== kind) {
      throw new Error(`${CONTENT_ERROR}"${group}/${name}" is a ${file.kind}, not a ${kind}`);
    }
    return file as Extract<Held, { kind: K }>;
  };

  return {
    manifest,
    load(group, loadOptions = {}) {
      entriesOf(group);
      const current = held.get(group);
      if (current) {
        return Promise.resolve({ group, loaded: current.size, failed: [] });
      }
      const running = loading.get(group);
      if (running) return running;
      const promise = run(group, loadOptions).finally(() => loading.delete(group));
      loading.set(group, promise);
      return promise;
    },
    unload(group) {
      entriesOf(group);
      const files = held.get(group);
      if (!files) return 0;
      held.delete(group);
      return free(files);
    },
    isLoaded: (group) => held.has(group),
    memory(group) {
      let total = 0;
      for (const file of held.get(group)?.values() ?? []) total += file.memory;
      return total;
    },
    size: (group) => entriesOf(group).reduce((sum, [, entry]) => sum + (entry.bytes ?? 0), 0),
    image(group, name) {
      return get(group, name, "image").image;
    },
    sound: (group, name) => get(group, name, "sound").buffer,
    data: (group, name) => get(group, name, "data").value,
    async fontsReady() {
      await Promise.allSettled([...fontLoads]);
      if (typeof document !== "undefined" && document.fonts) await document.fonts.ready;
    },
  };
}
