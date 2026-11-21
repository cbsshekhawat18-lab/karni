import type { AssetEntry } from "./manifest";

/** One file that did not load, with a reason a person can read. */
export interface AssetFailure {
  group: string;
  name: string;
  url: string;
  reason: string;
}

/** The error `load` throws when a file of the group would not load (after its retries). */
export class AssetLoadError extends Error {
  readonly group: string;
  readonly failures: readonly AssetFailure[];
  constructor(group: string, failures: readonly AssetFailure[]) {
    const shown = failures
      .slice(0, 5)
      .map((f) => `${f.name} (${f.reason})`)
      .join(", ");
    const more = failures.length > 5 ? ` and ${failures.length - 5} more` : "";
    super(
      `Could not load ${failures.length} file${failures.length === 1 ? "" : "s"} of "${group}": ${shown}${more}`,
    );
    this.name = "AssetLoadError";
    this.group = group;
    this.failures = failures;
  }
}

/** The pieces of the browser the loader uses. Each can be replaced (tests do, and so can a game). */
export interface Platform {
  fetch(url: string, init?: { signal?: AbortSignal }): Promise<Response>;
  /** Decode an image off the main thread. Default `createImageBitmap`, else an `<img>` decoded with `decode()`. */
  decodeImage(blob: Blob): Promise<ImageSource>;
  /** Add a font so CSS and canvas text can use it. Resolves a handle `removeFont` takes. */
  addFont(family: string, data: ArrayBuffer, descriptors: FontFaceDescriptors): Promise<unknown>;
  removeFont(handle: unknown): void;
  /** Does this browser decode WebP? */
  webp(): Promise<boolean>;
  wait(ms: number): Promise<void>;
}

/** A decoded image a drawing layer can pass to `drawImage`. */
export interface ImageSource {
  source: CanvasImageSource;
  width: number;
  height: number;
  /** Free the pixels (an ImageBitmap's `close`). */
  close(): void;
}

/** A tiny lossy WebP: the browser decoding it means it decodes any WebP. */
const WEBP_PROBE =
  "data:image/webp;base64,UklGRiIAAABXRUJQVlA4IBYAAAAwAQCdASoBAAEADsD+JaQAA3AAAAAA";

export function browserPlatform(): Platform {
  let webp: Promise<boolean> | null = null;
  return {
    fetch: (url, init) => fetch(url, init),
    async decodeImage(blob) {
      if (typeof createImageBitmap === "function") {
        const bitmap = await createImageBitmap(blob);
        return {
          source: bitmap,
          width: bitmap.width,
          height: bitmap.height,
          close: () => bitmap.close(),
        };
      }
      const url = URL.createObjectURL(blob);
      const image = new Image();
      image.src = url;
      try {
        await image.decode();
      } catch (error) {
        URL.revokeObjectURL(url);
        throw error;
      }
      return {
        source: image,
        width: image.naturalWidth,
        height: image.naturalHeight,
        close: () => URL.revokeObjectURL(url),
      };
    },
    async addFont(family, data, descriptors) {
      const face = new FontFace(family, data, descriptors);
      await face.load();
      document.fonts.add(face);
      return face;
    },
    removeFont: (handle) => void document.fonts.delete(handle as FontFace),
    webp() {
      webp ??= new Promise<boolean>((done) => {
        if (typeof Image === "undefined") return done(false);
        const image = new Image();
        image.onload = () => done(image.width > 0);
        image.onerror = () => done(false);
        image.src = WEBP_PROBE;
      });
      return webp;
    },
    wait: (ms) => new Promise((done) => setTimeout(done, ms)),
  };
}

export function formatOf(entry: AssetEntry): "json" | "text" | "binary" {
  if (entry.format) return entry.format;
  const path = entry.url.split(/[?#]/)[0]?.toLowerCase() ?? "";
  if (path.endsWith(".json")) return "json";
  if (path.endsWith(".txt") || path.endsWith(".csv") || path.endsWith(".tsv")) return "text";
  return "binary";
}
