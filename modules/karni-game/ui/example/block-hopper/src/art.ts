import type { View } from "@karni/game";
import {
  REDUCED_MOTION,
  createCamera,
  createParticles,
  createRenderer,
  createSprite,
  textStyle,
  type Painter,
  type Sprite,
} from "@karni/game/draw";
import { WORLD, score, type Hopper } from "./rules";
import type { GameAssets, StageInfo, StageName } from "./stages";

/** What the drawing reads from the game each frame. */
export interface ArtSource {
  hopper(): Hopper;
  stage(): { name: StageName; info: StageInfo } | null;
  best(): number;
  adPlaying(): boolean;
  /** Extra drawing on top of the HUD: the touch stick. */
  overlay?(context: CanvasRenderingContext2D): void;
}

export interface ArtOptions {
  canvas: HTMLCanvasElement;
  view: View;
  assets: GameAssets;
  source: ArtSource;
}

/**
 * Block Hopper's drawing on @karni/game/draw: a camera that follows the block,
 * the stage's backdrop on a parallax layer, the platforms, coins and block,
 * particles, and the HUD. Sprites are cut from images of the asset groups
 * (`createSprite(assets.image(...))`): until a group loads, and after it
 * unloads, `g.sprite` draws nothing and returns false, and shapes stand in.
 */
export function createArt({ canvas, view, assets, source }: ArtOptions) {
  // The camera keeps the block a third of the way across, and never shows left of the start.
  const camera = createCamera({
    view,
    offset: { x: -WORLD.width / 6, y: 0 },
    bounds: { x: 0, y: 0, w: Infinity, h: WORLD.height },
  });
  const renderer = createRenderer({
    canvas,
    view,
    camera,
    background: "#0d1b2a",
    layers: [
      { name: "sky", screen: true },
      // The stage's backdrop moves at a quarter of the platforms' speed.
      { name: "backdrop", parallax: 0.25 },
      "world",
      "effects",
      { name: "hud", screen: true },
    ],
  });
  const effects = createParticles({ max: 120 });
  const sparkle = effects.emitter({
    speed: [40, 110],
    life: [0.25, 0.5],
    size: [2, 4],
    colors: ["#ffd166", "#fff3c4"],
  });
  const dust = effects.emitter({
    speed: [10, 40],
    angle: [Math.PI, Math.PI * 2],
    life: [0.2, 0.35],
    size: 3,
    colors: ["#778da9"],
  });
  // An outline keeps the HUD readable over a light sky and a dark cave alike.
  const text = textStyle({
    font: "bold 14px system-ui, sans-serif",
    fill: "#f8f9fa",
    stroke: "#0d1b2a",
    strokeWidth: 3,
  });

  let core: { hopper: Sprite; coin: Sprite } | null = null;
  let backdrop: { stage: StageName; sprite: Sprite } | null = null;

  renderer.on("sky", (g) => g.rect(0, 0, WORLD.width, WORLD.height, "#1b263b"));
  renderer.on("backdrop", (g) => {
    const stage = source.stage();
    if (!stage || !assets.isLoaded(stage.name)) return;
    if (backdrop?.stage !== stage.name) {
      backdrop = { stage: stage.name, sprite: createSprite(assets.image(stage.name, "bg")) };
    }
    const { sprite } = backdrop;
    // The art repeats at its own width across what this layer shows.
    const first = Math.floor(g.left / sprite.w) * sprite.w;
    for (let x = first; x < g.left + g.width; x += sprite.w) g.sprite(sprite, x, 0);
  });
  renderer.on("world", (g) => {
    const hopper = source.hopper();
    const platform = source.stage()?.info.platform ?? "#778da9";
    // Off-screen platforms and coins are culled by the painter.
    for (const p of hopper.platforms) g.rect(p.x, p.y, p.w, p.h, platform);
    for (const c of hopper.pickups) {
      if (c.taken || !g.visible(c.x - 5, c.y - 5, 10, 10)) continue;
      if (!core || !g.sprite(core.coin, c.x, c.y)) g.rect(c.x - 5, c.y - 5, 10, 10, "#ffd166");
    }
    if (!core || !g.sprite(core.hopper, hopper.x, hopper.y)) {
      g.rect(hopper.x, hopper.y, hopper.w, hopper.h, "#ef476f");
    }
  });
  renderer.on("effects", (g) => effects.draw(g));
  renderer.on("hud", (g: Painter) => {
    g.text(`Score ${score(source.hopper())}   Best ${source.best()}`, 10, 8, text);
    if (source.adPlaying()) g.text("Ad playing...", 200, 240, text);
    source.overlay?.(g.ctx);
  });

  return {
    camera,
    effects,
    renderer,
    /** Cut the sprites of the core group: call it after the group loads. */
    useCore(): void {
      core = {
        hopper: createSprite(assets.image("core", "hopper")),
        coin: createSprite(assets.image("core", "coin"), { anchor: [0.5, 0.5] }),
      };
    },
    /** Follow a new run's block from where it stands. */
    follow(hopper: Hopper): void {
      camera.follow(hopper);
      camera.snap();
      effects.clear();
    },
    coin: (x: number, y: number): void => sparkle.burst(x, y, 12),
    land: (x: number, y: number): void => dust.burst(x, y, 6),
    /** The player's reduced-motion setting scales the shake and the particles down. */
    reduceMotion(reduced: boolean): void {
      camera.motion = reduced ? REDUCED_MOTION : 1;
      effects.motion = reduced ? REDUCED_MOTION : 1;
    },
    render(alpha: number, dt: number): void {
      camera.update(dt);
      renderer.render(alpha, dt);
    },
  };
}
