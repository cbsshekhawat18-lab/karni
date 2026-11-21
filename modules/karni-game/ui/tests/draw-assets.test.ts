import { describe, expect, it } from "vitest";
import { createAssets, defineManifest, type ImageSource } from "@karni/game/assets";
import {
  createAnimator,
  createRenderer,
  createSprite,
  defineClips,
  sheetFrames,
} from "../src/draw";
import { fakeImage, fakeView, must, ops, recordingContext } from "./fake-canvas";

/**
 * The 2D layer and the asset loader together: a sprite sheet and its frame
 * data load as one group, the sheet is cut and drawn by @karni/game/draw,
 * and an unloaded group draws nothing.
 */
const manifest = defineManifest({
  groups: {
    hero: {
      sheet: { kind: "image", url: "img/hero.png", bytes: 400 },
      // An atlas is a plain image, with its frame data as a data file in the same group.
      frames: { kind: "data", url: "data/hero.json", bytes: 80 },
    },
  },
});

const FRAMES = { frameWidth: 16, frameHeight: 16, clips: { run: { frames: [0, 1, 2, 3] } } };

function loader() {
  const sheet = fakeImage(64, 16);
  const assets = createAssets({
    manifest,
    platform: {
      fetch: async (url) =>
        new Response(url.endsWith(".json") ? JSON.stringify(FRAMES) : "png", { status: 200 }),
      decodeImage: async (): Promise<ImageSource> => ({
        source: sheet,
        width: sheet.width,
        height: sheet.height,
        // As ImageBitmap.close() does: a closed bitmap has no size.
        close: () => {
          sheet.width = 0;
          sheet.height = 0;
        },
      }),
      webp: async () => false,
      wait: async () => undefined,
    },
  });
  return { assets, sheet };
}

describe("sprites from an asset group", () => {
  it("cuts a sheet loaded through a group, by the group's frame data, and draws its frames", async () => {
    const { assets, sheet } = loader();
    await assets.load("hero");
    const data = assets.data("hero", "frames") as typeof FRAMES;
    // createSprite and sheetFrames take assets.image(...) as it comes: { source, width, height }.
    const frames = sheetFrames(assets.image("hero", "sheet"), data.frameWidth, data.frameHeight, {
      anchor: [0.5, 1],
    });
    expect(frames).toHaveLength(4);
    expect(frames[2]).toMatchObject({ image: sheet, sx: 32, sw: 16, sh: 16 });
    const whole = createSprite(assets.image("hero", "sheet"));
    expect(whole).toMatchObject({ image: sheet, sw: 64, sh: 16 });

    const clips = defineClips(frames, { run: { frames: data.clips.run.frames, fps: 10 } });
    const animator = createAnimator(clips, "run");
    animator.update(0.25);
    const { context, calls } = recordingContext();
    const renderer = createRenderer({
      context,
      view: fakeView(1, 1),
      layers: [{ name: "world", screen: true }],
    });
    renderer.on("world", (g) => {
      g.sprite(must(frames[2]), 100, 50);
      g.sprite(animator.sprite, 200, 50);
    });
    renderer.render();
    const draws = ops(calls, "drawImage");
    expect(draws).toHaveLength(2);
    expect(draws[0]?.args).toEqual([32, 0, 16, 16, 92, 34, 16, 16]);
    expect(draws[1]?.args).toEqual([32, 0, 16, 16, 192, 34, 16, 16]);
  });

  it("draws nothing from a group once it is unloaded, so a game can fall back to shapes", async () => {
    const { assets } = loader();
    await assets.load("hero");
    const sprite = createSprite(assets.image("hero", "sheet"), { w: 16, h: 16 });
    assets.unload("hero");
    expect(assets.isLoaded("hero")).toBe(false);
    const { context, calls } = recordingContext();
    const renderer = createRenderer({
      context,
      view: fakeView(1, 1),
      layers: [{ name: "world", screen: true }],
    });
    let drawn: boolean | null = null;
    renderer.on("world", (g) => {
      drawn = g.sprite(sprite, 10, 10);
      if (!drawn) g.rect(10, 10, 16, 16, "#ef476f");
    });
    renderer.render();
    expect(drawn).toBe(false);
    expect(ops(calls, "drawImage")).toHaveLength(0);
    expect(ops(calls, "fillRect").map((call) => call.fill)).toContain("#ef476f");
  });
});
