---
description: "@karni/game/draw (experimental): a light 2D layer on Canvas 2D for browser games. Layers drawn in order, a camera with follow, dead zone, bounds, shake and zoom, shapes, text with a layout cache, sprites and frame animation, tweens and easing, pooled particles, an object pool, and time scale and hit-stop on the loop."
---

# Drawing (@karni/game/draw)

!!! warning "Experimental"
    `@karni/game/draw` is [experimental](stability.md#experimental-names): a
    name or an option may change in a minor release, with a CHANGELOG entry.

`@karni/game/draw` is what a game on plain canvas writes before its own
rules: layers drawn in order, a camera, shapes and text in game units,
sprites cut from sheets and animated, tweens, particles and a pool. It draws
on Canvas 2D over the view of [`@karni/game`](game-client.md#the-loop-the-view-and-pauses)
(`createView`), so the virtual resolution, the letterbox and the pixel-ratio
cap come with it.

It is small on purpose. There is no WebGL, no scene graph beyond layers and
no entity system: a game keeps its own list of things and draws it from a
layer. A game that needs batching, filters or thousands of moving sprites
moves to an engine and the [PixiJS adapter](game-client.md#engines).
Collision is its own entry point, [`@karni/game/collide`](game-collide.md).

The entry point has no dependency and every export is tree-shaken: a game
that imports only `createPool` bundles only the pool.

## A frame in one page

```ts
import { createLoop, createView } from "@karni/game";
import { createCamera, createParticles, createRenderer, textStyle } from "@karni/game/draw";

const view = createView({ canvas, width: 480, height: 270 });
const camera = createCamera({
  view,
  bounds: { x: 0, y: 0, w: 1600, h: 540 },
  deadZone: { w: 60, h: 50 },
  smoothing: 7,
});
camera.follow(player); // any object with x, y (and w, h)

const renderer = createRenderer({
  canvas,
  view,
  camera,
  background: "#0b132b",
  layers: [
    { name: "sky", screen: true },
    { name: "hills", parallax: 0.35 },
    "world",
    "effects",
    { name: "hud", screen: true },
  ],
});
const sparks = createParticles({ max: 400 });
const score = textStyle({ font: "bold 14px system-ui", fill: "#fff3c4", stroke: "#0b132b" });

renderer.on("sky", (g) => g.rect(0, 0, 480, 270, "#1c2541"));
renderer.on("world", (g) => {
  for (const crate of level.crates) g.sprite(art.crate, crate.x, crate.y);
  g.sprite(hero.sprite, player.x, player.y, player.facing, 1);
});
renderer.on("effects", (g) => sparks.draw(g));
renderer.on("hud", (g) => g.text(`Gems ${gems}`, 8, 8, score));

const loop = createLoop({
  step: 1 / 120,
  update: (dt) => {
    world.step(dt);
    sparks.update(dt);
  },
  render: (alpha, dt) => {
    camera.update(dt);
    renderer.render(alpha, dt);
  },
});
```

The example scene `modules/karni-game/ui/example/crate-climb/` is this,
whole: a level three screens wide, crates and ledges, gems, a flag, and
every piece of this page in use (`npm run example:climb`).

## Layers and the renderer

`createRenderer({ canvas, view, camera, layers })` draws a frame from
layers, bottom first. A layer is a list of draw functions, each called
with the painter `g`, the loop's leftover step fraction `alpha` and the
frame time `dt`.

- `renderer.on(layer, fn)` adds a draw function and returns its remover.
  A scene adds its functions when it starts and removes them when it ends.
- A layer's options: `order` (lower draws first, default its place in the
  list), `screen` (game units, no camera: a HUD or a backdrop), `parallax`
  (how much it moves and zooms with the camera: 1 is the world, 0.3 a far
  background, 0 does not move), `alpha`, `visible` and `cull`. Each can be
  changed on `renderer.layer(name)` at any time.
- Each frame fills the whole canvas with `background` (the letterbox bars
  too, or clears it with `null`), then keeps the drawing inside the game
  area (`clip`, default true).
- `smoothing: false` keeps scaled pixel art sharp.
- A draw function that throws is reported (`onError`, the console by
  default) and the other layers are drawn.
- `renderer.stats` counts what the last frame drew and culled.

## The camera

`createCamera({ view })` is a 2D camera. `x` and `y` are the world point at
the centre of the screen.

- `follow(target)` follows a point, or the centre of a box. The camera
  moves only when the target leaves the `deadZone` box around the centre,
  and `offset` keeps the target off centre (`{ x: -80 }` shows more ahead
  of a runner).
- `smoothing` is how fast it catches up, per second, the same at any frame
  rate. 0 snaps. `snap()` jumps to the target at once (a level start, a
  respawn).
- `bounds` keeps it inside the world. A world smaller than the screen is
  centred, and a bound can be open: `{ x: 0, y: 0, w: Infinity, h: 270 }`.
- `zoom` above 1 shows less of the world, larger, about the centre. Tween it
  for a close-up: `tweens.to(camera, { zoom: 1.6 }, 1.2, { ease: inOutSine })`.
- `shake(strength, seconds)` shakes by up to `strength` game units, fading
  out. A weaker shake does not cut a stronger one short.
- `sees(x, y, w, h)` tells whether a box of the world is on screen,
  `toScreen` and `toWorld` map points both ways (with `view.toGame` for a
  pointer).

Call `camera.update(dt)` once a frame. In `render`, with the real frame
time, the shake goes on during a [hit-stop](#time-scale-and-hit-stop) while
the world stands still.

## Shapes and text

The painter `g` draws in the layer's units: world units on a camera layer,
game units on a screen layer.

| Call | Draws |
|---|---|
| `g.rect(x, y, w, h, fill)`, `g.strokeRect(x, y, w, h, stroke, width)` | a box |
| `g.circle(x, y, r, fill)`, `g.strokeCircle(x, y, r, stroke, width)` | a circle |
| `g.line(x1, y1, x2, y2, stroke, width)` | a line |
| `g.poly([x0, y0, x1, y1, ...], fill, stroke, width)` | a closed polygon from flat coordinates |
| `g.text(text, x, y, style)` | text in a style made with `textStyle` |
| `g.sprite(sprite, x, y, scaleX, scaleY, rotation)` | a sprite, see below |

A fill or a stroke is a CSS colour, a gradient or a pattern. `g.alpha` sets
the opacity of what is drawn next, on top of the layer's.

Anything wholly outside the area a layer shows is skipped before it reaches
the canvas, so a level can draw all of its crates and only the ones on
screen cost anything. `g.visible(x, y, w, h)` asks the same question for a
draw of the game's own.

`textStyle({ font, fill, stroke, align, baseline, wrap, lineHeight })` is
made once and used every frame. It keeps the layout of each string it drew:
a string is measured (and broken into lines at `wrap` game units) the first
time, and later draws reuse that. The font is set on the canvas only when
the style changes. After a web font loads, `style.clearCache()` measures
again. `g.measure(text, style)` gives a layout's lines, width and height.

`g.ctx` is the raw 2D context, set to the layer's units: the escape hatch
for anything the helpers do not cover (a gradient made from it, a clip, a
composite mode). `createPainter(context)` gives the same helpers over a
context of your own, with no renderer.

## Sprites and frame animation

A sprite is a region of an image, drawn at a size in game units around an
anchor. The image is a loaded `<img>`, a canvas painted in code, an
`ImageBitmap`, or an image of an asset group as
[`@karni/game/assets`](game-assets.md) gives it.

```ts
const frames = sheetFrames(image, 16, 24, { anchor: [0.5, 1] }); // bottom centre
const clips = defineClips(frames, {
  idle: { frames: [0, 1], fps: 2 },
  run: { frames: { from: 2, to: 5 }, fps: 12 },
  land: { frames: [6, 7], fps: 20, loop: false },
});
const hero = createAnimator(clips, "idle");

hero.play(player.grounded ? "run" : "land"); // the same clip keeps playing
hero.update(dt);
g.sprite(hero.sprite, player.x, player.y, player.facing, 1); // -1 flips it
```

- `createSprite(image, { x, y, w, h, anchor, scale })` cuts one region,
  `sheetFrames(image, w, h, { margin, spacing, count })` cuts a grid.
- `g.sprite` returns false when the image has not loaded yet, so a game can
  draw a shape instead. A sprite with no rotation or scale is one
  `drawImage` call.
- `createAnimator(clips, first, onEnd)` plays one clip at a time:
  `speed`, `done` and `index` are there for the game's own logic.

### Sprites from an asset group

`createSprite` and `sheetFrames` take `assets.image(group, name)` as it comes
(`{ source, width, height }`). A sprite sheet is a plain image in a group, and
its frame data is a data file in the same group, so both load and unload
together:

```ts
await assets.load("hero");
const data = assets.data("hero", "frames") as { w: number; h: number };
const frames = sheetFrames(assets.image("hero", "sheet"), data.w, data.h, { anchor: [0.5, 1] });

renderer.on("world", (g) => {
  // Before the group loads, and after it unloads, g.sprite draws nothing and returns false.
  if (!g.sprite(hero.sprite, player.x, player.y)) g.rect(player.x - 8, player.y - 24, 16, 24, "#ef476f");
});
```

`assets.unload` closes the group's bitmaps, and a closed bitmap has no size,
so a sprite cut from it is skipped instead of drawn. Cut the sprites again
after the group loads again. Block Hopper draws its block, its coins and each
stage's backdrop this way, with shapes until the art arrives, and a test
loads a sheet and its frame data through a group and draws them
(`tests/draw-assets.test.ts`).

## Tweens and easing

```ts
const tweens = createTweens();
tweens.to(coin, { y: coin.y - 24, alpha: 0 }, 0.6, { ease: outQuad, onDone: () => remove(coin) });
tweens.to(counter, { scale: 1.6 }, 0.08, {
  onDone: () => tweens.to(counter, { scale: 1 }, 0.3, { ease: outBack }),
});
tweens.wait(2, () => spawnBoss());
// in update:
tweens.update(dt);
```

- `to(target, values, seconds, options)` moves number properties of any
  object: an entity, the camera, a layer, the loop's `timeScale`. A tween
  reads its start values when it starts (after `delay`), so tweens chained
  in `onDone` pick up where the last ended.
- Options: `ease`, `delay`, `repeat` (`Infinity` for ever), `yoyo` (there
  and back), `onUpdate`, `onDone`. `cancel()` stops one, `cancelOf(target)`
  stops every tween of a thing being removed.
- `wait(seconds, then)` is a timer on the same clock.
- Easing functions are separate exports, so a game bundles the ones it
  uses: `linear`, `inQuad`, `outQuad`, `inOutQuad`, `inCubic`, `outCubic`,
  `inOutCubic`, `inSine`, `outSine`, `inOutSine`, `inExpo`, `outExpo`,
  `inBack`, `outBack`, `outElastic`, `outBounce`, or any function from 0 to
  1 of your own.
- `damp(current, target, rate, dt)` moves a value toward a target the same
  way at any frame rate: a health bar, a cursor, a camera of your own.

A tween list updated in `update` runs on the game clock: it slows with the
time scale and stops during a hit-stop. A second list updated in `render`
with the real frame time suits the HUD and the camera.

## Particles and pools

```ts
const effects = createParticles({ max: 400 });
const sparkle = effects.emitter({
  speed: [40, 150],
  life: [0.3, 0.7],
  size: [2, 4],
  colors: ["#ffd166", "#fff3c4"],
  blend: "lighter",
});
const dust = effects.emitter({ speed: [20, 80], angle: [Math.PI, Math.PI * 2], gravity: 220 });

sparkle.burst(gem.x, gem.y, 18);
trail.flow(player.x, player.y, 30, dt); // 30 a second
effects.update(dt);
renderer.on("effects", (g) => effects.draw(g));
```

A particle system makes its `max` particles up front and reuses them, so
bursts and streams make no garbage. An emitter is one look: `speed`,
`angle`, `life` and `size` (a number, or a range picked from), `endSize`,
`colors`, `gravity`, `drag`, `fade`, `shape` (`"square"`, `"circle"` or a
sprite), `spread` and `blend`. Past the cap a burst is cut short.

`createPool({ create, reset, max, prefill })` is the pool the particles
use, for anything else a game spawns often: bullets, floating numbers,
enemies. `acquire()` hands out a free item (or null at `max`), `release`
gives one back, and `retain(keep)` visits the live items in order and gives
back the ones `keep` returns false for, in one pass.

## Time scale and hit-stop

These two are on the loop of [`@karni/game`](game-client.md#the-loop-the-view-and-pauses),
since they change what `update` receives:

- `loop.timeScale = 0.35` is slow motion. With a fixed step the step stays
  the same size and fewer steps run, so a seeded simulation stays
  deterministic. `render` keeps the real frame time.
- `loop.hitStop(70)` freezes the game for 70 real milliseconds, the pause
  on a heavy hit. `render` goes on, and a press made meanwhile reaches the
  first update after it. A second call keeps the longer of the two.

## Reduced motion

The camera's `motion` and the particles' `motion` (0 to 1) scale the shake
and the number of particles. Both start at 1, or at `REDUCED_MOTION` (0.25)
when the browser asks for less motion (`prefersReducedMotion()`). A game's
own setting wins: set both from its settings screen.

## Performance

- Culling skips what is off screen before any canvas call.
- The per-frame paths make no garbage: no object is made per thing per
  frame by the renderer, the painter, the camera, the animator, running
  tweens, the particles or the pool. A test bundles the entry points as a
  game would and checks the heap per frame in Node with 50 to 300 things on
  screen.
- A browser test draws 2000 animated sprites (some turned and scaled), 1500
  particles, 200 tweens and 50 bodies on the box mover in headless Chromium
  at 60 Hz, at desktop and phone size, and fails when the 95th percentile
  of a frame's work passes 12 ms (`KARNI_GAME_BENCH_BUDGET_MS` changes it).
- The entry point has a gzip size budget, checked by a test on a minified
  build: 7.1 KB for all of `@karni/game/draw`. A game bundles only what it
  imports.

## Escape hatches

- `g.ctx` is the raw context in the layer's units, `createPainter` works on
  any context, and a draw function can draw anything.
- `renderer.layer(name)` changes a layer's order, parallax, opacity,
  visibility and culling at run time.
- The camera takes its own `random` source, the particles theirs (a seeded
  one in a test), and both take a `motion` scale.
- Easing is any function, the pool takes the game's own `create` and
  `reset`.

## What it does not do

- No WebGL renderer or sprite batcher, no filters or shaders, no lighting.
  A game that needs them moves to PixiJS and the adapter.
- No scene graph and no entity-component system: layers hold draw
  functions, the game holds its own list of things.
- No tilemaps and no atlas packer. Engines bring their own, and a canvas
  game draws a grid of sprites from a layer.
- No loading of its own: images come from [`@karni/game/assets`](game-assets.md)
  or from the game.
