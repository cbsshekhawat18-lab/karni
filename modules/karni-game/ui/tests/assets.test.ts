import { describe, expect, it } from "vitest";
import {
  AssetLoadError,
  createAssets,
  defineManifest,
  type ImageSource,
  type LoadProgress,
  type Platform,
} from "@karni/game/assets";

const manifest = defineManifest({
  groups: {
    core: {
      ui: { kind: "font", url: "fonts/ui.woff2", bytes: 100, family: "Game UI", weight: "700" },
      config: { kind: "data", url: "data/config.json", bytes: 50 },
    },
    stage1: {
      sky: { kind: "image", url: "img/sky.png", webp: "img/sky.webp", bytes: 300 },
      hero: { kind: "image", url: "img/hero.png", bytes: 100 },
      boing: { kind: "sound", url: "snd/boing.ogg", bytes: 50 },
      levels: { kind: "data", url: "data/levels.csv", bytes: 10 },
    },
  },
});

interface Rig {
  platform: Partial<Platform>;
  fetched: string[];
  closed: string[];
  fonts: { family: string; weight?: string }[];
  removed: unknown[];
  waits: number[];
  fail: Map<string, number>;
  webp: boolean;
}

function rig(): Rig {
  const state: Rig = {
    platform: {},
    fetched: [],
    closed: [],
    fonts: [],
    removed: [],
    waits: [],
    fail: new Map(),
    webp: true,
  };
  const bodies: Record<string, string> = {
    "data/config.json": '{"gravity":9}',
    "data/levels.csv": "a,b\n1,2",
    "https://cdn.example.com/a.json": "{}",
    "/x.json": "{}",
    "data:application/json,%7B%7D": "{}",
  };
  state.platform = {
    async fetch(url) {
      state.fetched.push(url);
      const left = state.fail.get(url);
      if (left === undefined) {
        // fine
      } else if (left === Infinity || left > 0) {
        if (left !== Infinity) state.fail.set(url, left - 1);
        return new Response("nope", { status: 404 });
      }
      return new Response(bodies[url] ?? "bytes", { status: 200 });
    },
    async decodeImage(blob): Promise<ImageSource> {
      const name = String(blob.size);
      return {
        source: {} as CanvasImageSource,
        width: 10,
        height: 20,
        close: () => void state.closed.push(name),
      };
    },
    async addFont(family, _data, descriptors) {
      state.fonts.push({ family, weight: descriptors.weight });
      return { family };
    },
    removeFont: (handle) => void state.removed.push(handle),
    webp: async () => state.webp,
    wait: async (ms) => void state.waits.push(ms),
  };
  return state;
}

const audio = {
  decode: async (data: ArrayBuffer) =>
    ({ length: 100, numberOfChannels: 2, byteLength: data.byteLength }) as unknown as AudioBuffer,
};

describe("createAssets", () => {
  it("loads a group with progress that only goes forward and ends at 1", async () => {
    const r = rig();
    const assets = createAssets({ manifest, audio, platform: r.platform });
    const seen: LoadProgress[] = [];
    const report = await assets.load("stage1", { onProgress: (p) => seen.push(p) });
    expect(report).toEqual({ group: "stage1", loaded: 4, failed: [] });
    expect(seen[0]).toMatchObject({ loaded: 0, total: 4, fraction: 0, bytesTotal: 460 });
    expect(seen.at(-1)).toMatchObject({ loaded: 4, fraction: 1, bytesLoaded: 460 });
    for (let i = 1; i < seen.length; i += 1) {
      expect(seen[i]?.fraction).toBeGreaterThanOrEqual(seen[i - 1]?.fraction ?? 0);
    }
    expect(assets.isLoaded("stage1")).toBe(true);
    expect(assets.size("stage1")).toBe(460);
  });

  it("gives typed access to each kind and names what exists when a name is wrong", async () => {
    const r = rig();
    const assets = createAssets({ manifest, audio, platform: r.platform });
    expect(() => assets.image("stage1", "hero")).toThrow(/not loaded: call load\("stage1"\)/);
    await assets.load("stage1");
    await assets.load("core");
    expect(assets.image("stage1", "hero")).toMatchObject({ width: 10, height: 20 });
    expect(assets.sound("stage1", "boing").numberOfChannels).toBe(2);
    expect((assets.data("core", "config") as { gravity: number }).gravity).toBe(9);
    expect(assets.data("stage1", "levels")).toBe("a,b\n1,2");
    expect(() => assets.image("stage1", "nope" as "hero")).toThrow(/no file "nope".*hero/);
    expect(() => assets.sound("stage1", "hero")).toThrow(/is a image, not a sound/);
    // @ts-expect-error a group the manifest does not have
    expect(() => assets.load("stage9")).toThrow(/no group "stage9".*core, stage1/);
  });

  it("adds fonts before the load resolves, with the family and weight of the entry", async () => {
    const r = rig();
    const assets = createAssets({ manifest, platform: r.platform });
    await assets.load("core");
    expect(r.fonts).toEqual([{ family: "Game UI", weight: "700" }]);
    await assets.fontsReady();
  });

  it("shares one load between callers and returns at once for a loaded group", async () => {
    const r = rig();
    const assets = createAssets({ manifest, audio, platform: r.platform });
    const [a, b] = await Promise.all([assets.load("stage1"), assets.load("stage1")]);
    expect(a).toBe(b);
    const count = r.fetched.length;
    await assets.load("stage1");
    expect(r.fetched.length).toBe(count);
  });

  it("unloads a group: bitmaps closed, fonts removed, memory counted, and the group reloads", async () => {
    const r = rig();
    const assets = createAssets({ manifest, audio, platform: r.platform });
    await assets.load("stage1");
    await assets.load("core");
    // image 10x20x4 twice, a sound of 100 frames x 2 channels x 4, and 7 chars of text x 2.
    expect(assets.memory("stage1")).toBe(2 * 800 + 800 + 14);
    expect(assets.unload("stage1")).toBe(2 * 800 + 800 + 14);
    expect(r.closed).toHaveLength(2);
    expect(assets.isLoaded("stage1")).toBe(false);
    expect(assets.memory("stage1")).toBe(0);
    expect(() => assets.image("stage1", "hero")).toThrow(/not loaded/);
    assets.unload("core");
    expect(r.removed).toEqual([{ family: "Game UI" }]);
    expect(assets.unload("core")).toBe(0);
    await assets.load("stage1");
    expect(assets.isLoaded("stage1")).toBe(true);
  });

  it("prefers the WebP copy and falls back to the original once, where it cannot be used", async () => {
    const a = rig();
    await createAssets({ manifest, audio, platform: a.platform }).load("stage1");
    expect(a.fetched).toContain("img/sky.webp");
    expect(a.fetched).not.toContain("img/sky.png");

    const b = rig();
    b.webp = false;
    await createAssets({ manifest, audio, platform: b.platform }).load("stage1");
    expect(b.fetched).toContain("img/sky.png");
    expect(b.fetched).not.toContain("img/sky.webp");

    const c = rig();
    c.fail.set("img/sky.webp", Infinity);
    await createAssets({ manifest, audio, platform: c.platform }).load("stage1");
    expect(c.fetched.filter((u) => u === "img/sky.webp")).toHaveLength(1);
    expect(c.fetched).toContain("img/sky.png");

    const d = rig();
    await createAssets({ manifest, audio, platform: d.platform, webp: false }).load("stage1");
    expect(d.fetched).not.toContain("img/sky.webp");
  });

  it("retries a failed file with a growing wait and then succeeds", async () => {
    const r = rig();
    r.fail.set("img/hero.png", 2);
    const assets = createAssets({ manifest, audio, platform: r.platform });
    await assets.load("stage1");
    expect(r.fetched.filter((u) => u === "img/hero.png")).toHaveLength(3);
    expect(r.waits).toEqual([250, 500]);
  });

  it("fails with a readable error that names each file, and frees what had loaded", async () => {
    const r = rig();
    r.fail.set("img/hero.png", Infinity);
    r.fail.set("snd/boing.ogg", Infinity);
    const assets = createAssets({ manifest, audio, platform: r.platform, retries: 1 });
    const error = await assets.load("stage1").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(AssetLoadError);
    const failure = error as AssetLoadError;
    expect(failure.message).toBe(
      'Could not load 2 files of "stage1": hero (HTTP 404), boing (HTTP 404)',
    );
    expect(failure.failures.map((f) => f.name).sort()).toEqual(["boing", "hero"]);
    expect(assets.isLoaded("stage1")).toBe(false);
    expect(r.closed).toHaveLength(1);
  });

  it("goes on with strict: false and lists what failed", async () => {
    const r = rig();
    r.fail.set("img/hero.png", Infinity);
    const assets = createAssets({ manifest, audio, platform: r.platform, retries: 0 });
    const report = await assets.load("stage1", { strict: false });
    expect(report.loaded).toBe(3);
    expect(report.failed).toEqual([
      { group: "stage1", name: "hero", url: "img/hero.png", reason: "HTTP 404" },
    ]);
    expect(assets.isLoaded("stage1")).toBe(true);
  });

  it("refuses a host the build did not allow and never fetches from it", async () => {
    const r = rig();
    const remote = defineManifest({
      groups: {
        g: {
          ok: { kind: "data", url: "https://cdn.example.com/a.json" },
          bad: { kind: "data", url: "https://evil.example.net/b.json" },
          inline: { kind: "data", url: "data:application/json,%7B%7D" },
          rooted: { kind: "data", url: "/x.json" },
        },
      },
    });
    const assets = createAssets({
      manifest: remote,
      platform: r.platform,
      allowHosts: ["cdn.example.com"],
      retries: 0,
    });
    const report = await assets.load("g", { strict: false });
    expect(report.failed.map((f) => [f.name, f.reason])).toEqual([
      ["bad", "evil.example.net is not an allowed host (allowHosts)"],
    ]);
    expect(r.fetched.sort()).toEqual([
      "/x.json",
      "data:application/json,%7B%7D",
      "https://cdn.example.com/a.json",
    ]);
    const none = createAssets({ manifest: remote, platform: rig().platform, retries: 0 });
    expect((await none.load("g", { strict: false })).failed).toHaveLength(2);
  });

  it("says plainly that sounds need the audio layer", async () => {
    const r = rig();
    const assets = createAssets({ manifest, platform: r.platform, retries: 0 });
    await expect(assets.load("stage1")).rejects.toThrow(/boing \(createAssets needs `audio`/);
  });

  it("stops when cancelled and keeps nothing", async () => {
    const r = rig();
    const controller = new AbortController();
    const slow: Partial<Platform> = {
      ...r.platform,
      fetch: async (url, init) => {
        await new Promise<void>((done, fail) => {
          init?.signal?.addEventListener("abort", () => fail(new Error("aborted")));
          setTimeout(done, 1000);
        });
        return r.platform.fetch?.(url, init) as Promise<Response>;
      },
    };
    const assets = createAssets({ manifest, audio, platform: slow, retries: 0 });
    const loading = assets.load("stage1", { signal: controller.signal });
    controller.abort();
    await expect(loading).rejects.toThrow(/was cancelled/);
    expect(assets.isLoaded("stage1")).toBe(false);
  });

  it("times out a fetch that never answers and reports it", async () => {
    const r = rig();
    const hang: Partial<Platform> = {
      ...r.platform,
      fetch: (_url, init) =>
        new Promise((_done, fail) =>
          init?.signal?.addEventListener("abort", () => fail(new Error("aborted"))),
        ),
    };
    const assets = createAssets({ manifest, audio, platform: hang, retries: 0, timeout: 20 });
    const report = await assets.load("core", { strict: false });
    expect(report.failed.map((f) => f.reason)).toEqual(["timed out", "timed out"]);
  });
});
