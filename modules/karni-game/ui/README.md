# @karni/game

> **Experimental.** Its names may change in a minor release, with a CHANGELOG entry ([stability](https://cbsshekhawat18-lab.github.io/karni/stability/#experimental-names)).

The browser side of the Karni game add-on: portal and ad adapters, a canvas loop, input, audio,
local saves, a seeded random generator, an offline-first data client, per-portal builds, and a
light 2D layer for drawing and collision on plain canvas.

[![npm](https://img.shields.io/npm/v/@karni/game)](https://www.npmjs.com/package/@karni/game) [![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/cbsshekhawat18-lab/karni/blob/main/LICENSE) [![Docs](https://img.shields.io/badge/docs-online-FB5D08)](https://cbsshekhawat18-lab.github.io/karni/game-client/)

It works with no server at all: saves, boards, a wallet and a daily seed live on the device. The
karni-game module on a Karni server is an upgrade, not a requirement: the same calls then go to
the server, and writes made offline wait in a queue and are sent with their intents. The core has
no runtime dependency, every export is tree-shaken, and the package is ESM.

## Install

```bash
npm install @karni/game
```

Vite (for the preset), Playwright (for the smoke harness), React Three Fiber and React (for the
`r3f` hooks) are optional peers: install the ones a game uses.

## What is in it

| Import                                                      | What it gives                                                                                         |
| ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `@karni/game`                                               | the portal, the loop and view, input, audio, the save layer, the random generator and the data client |
| `@karni/game/portals/<name>`                                | one portal's adapter: `none`, `fake`, `poki`, `crazygames`, `gamedistribution`, `y8`                  |
| `@karni/game/draw`                                          | layers, a camera, shapes, text, sprites and frame animation, tweens, particles, a pool                |
| `@karni/game/collide`                                       | boxes and circles, overlap and sweep tests, a ray cast, the box mover, trigger zones                  |
| `@karni/game/vite`                                          | `karniGame()`, the Vite preset                                                                        |
| `@karni/game/build`                                         | the portal table, the package checks, `packagePortals`, `zipFolder`                                   |
| `@karni/game/phaser`, `@karni/game/pixi`, `@karni/game/r3f` | the engine adapters                                                                                   |
| `@karni/game/scenes`                                        | the scene stack, overlays, transitions, the entity list and the store                                 |
| `@karni/game/sim`                                           | the simulation contract, recorder, replay, state hash and test kit                                    |
| `@karni/game/assets`                                        | the asset manifest and loader: groups, progress, unloading, fonts, WebP copies, budgets               |
| `@karni/game/sfx`                                           | procedural sounds, one-shots with variation, music with crossfade and ducking                         |
| `@karni/game/smoke`                                         | `runSmoke`, the browser smoke harness                                                                 |
| `@karni/game/ui`                                            | the DOM UI kit: settings, pause, dialogs, toasts, touch buttons, boot failure screen, dev overlay     |
| `@karni/game/client`                                        | types for `virtual:karni-game/portal` and `__KARNI_GAME_DEV__`                                        |

The command `karni-game` lists the portals, packages a game for each and checks a package.

## A game in one page

```ts
import {
  POINTER,
  createAudio,
  createGameClient,
  createInput,
  createLoop,
  createPortal,
  createSave,
  createStorage,
  createView,
  linkPortal,
  pauseOnHidden,
} from "@karni/game";
import { createPortalAdapter } from "virtual:karni-game/portal";

const canvas = document.querySelector("canvas") as HTMLCanvasElement;
const storage = createStorage({ namespace: "block-hopper" });
const save = createSave({ storage, version: 1, defaults: () => ({ best: 0 }) });
const progress = save.load().data;

const portal = createPortal(createPortalAdapter());
const client = createGameClient({ game: "block-hopper", storage });
const view = createView({ canvas, width: 480, height: 270 });
const input = createInput({ target: canvas, view, bindings: { jump: ["Space", POINTER] } });
const audio = createAudio();
audio.unlockOn(input);

const loop = createLoop({
  step: 1 / 120,
  update: (dt) => {
    /* the game's rules, in fixed steps */
  },
  render: () => view.apply(canvas.getContext("2d") as CanvasRenderingContext2D),
  afterFrame: () => input.endFrame(),
});
pauseOnHidden([loop, audio]);
linkPortal(portal, { audio, loop, input });

await Promise.all([portal.init(), client.boot()]);
await client.signInGuest();
portal.loadingFinished();
loop.start();
```

`example/block-hopper/` is a whole game on these pieces (move, jump, score, save, a leaderboard
and a rewarded continue), and the browser tests play it. `example/crate-climb/` is a scene for the
2D layer below.

## The pieces

- **Portal and ads.** `createPortal(adapter, options)` puts a time limit on the SDK's start (the
  game boots without it), sends gameplay start and stop in pairs, keeps a cooldown between
  interstitials, gives a reward only on the SDK's completed event, and emits `adstart` and
  `adend` so `linkPortal` mutes and pauses around each ad. Without an SDK every call is a no-op.
  A portal's ids come from the project's config, never from the source.
- **Loop and view.** `createLoop` clamps the frame time, runs an optional fixed step with a step
  cap (`createFixedStep`), keeps a frame that throws from stopping the game, and pauses for named
  reasons. `pauseOnHidden` pauses on a hidden tab and on blur. `createView` caps the pixel ratio
  (lower on touch) and fits a virtual resolution with letterboxing.
- **Input.** `createInput` gives held, pressed and released per action for keys, mouse, touch and
  pen, cleared once a frame, and a first-gesture hook. `createVirtualStick` is a floating touch
  stick that presses the same bindings.
- **Audio.** `createAudio` unlocks on the first gesture and keeps master, music and effects
  volumes. The player's, the ad's and the portal's mutes are kept apart.
- **Saves.** `createStorage` probes the browser's storage and falls back to memory, with
  namespaced keys and a portal's data module read first. `createSave` keeps a versioned save
  with ordered migrations: a corrupt or newer save boots with the defaults and the copy is kept.
- **Random.** `createRng(seed)` (int, float, pick, shuffle, forks, a resumable state), `dateSeed`
  and `deviceDailySeed`.
- **Data client.** `createGameClient` signs in a guest (offline too), upgrades the guest to an
  account through Karni's sign-in, keeps save slots with the server's version counter and a
  conflict rule, submits scores with their runs, reads boards, the wallet, the shop, rewards,
  daily content, achievements and missions, remote config and flags, and batches analytics. A
  project with `@karni/ui` passes its own client as the `transport`, so calls carry the account.

## Simulation and replay

`@karni/game/sim` is the contract for a game's rules: plain state, a `step` over fixed ticks,
inputs as data and the seeded generator. A run is its seed and the inputs that changed, so it
replays to the same state hash. No clock and no `Math.random` in the rules, and a check enforces it.

```ts
import { checkDeterminism, createRecorder, defineSim, fuzz, verify } from "@karni/game/sim";

const rules = defineSim<{ x: number }, { right: boolean }>({
  idle: { right: false },
  init: () => ({ x: 0 }),
  step: (state, input, ctx) => {
    state.x += input.right ? 200 * ctx.dt : 0;
  },
  randomInput: (rng) => ({ right: rng.chance(0.5) }),
});

const recorder = createRecorder(rules, { seed: 7 });
recorder.step({ right: true });
verify(rules, recorder.finish()).ok; // true: the replay reaches the recorded hash
checkDeterminism(rules, { seed: 7, ticks: 300 });
fuzz(rules, { runs: 10, ticks: 300 });
```

`toRunRecord(recording)` makes the `run` of a score, with no change on the server. `createSimLoop`
runs a sim on the loop's fixed step. `karni-game check-rules` fails on a clock, outside randomness,
the page or the network in `src/rules/`, and a marker with a reason allows one use. See
[Simulation and replay](https://cbsshekhawat18-lab.github.io/karni/game-sim/).

## Scenes

`@karni/game/scenes` is the switch between a game's screens: a stack with `push`, `pop` and
`replace`, overlays that pause the scene below, a fade between scenes that is instant when the
player prefers reduced motion, an entity list with tags and safe removal, and a store for
settings and progress on the save layer. A scene gets the loop, input, audio, save, portal and
client from the stack and imports no global.

```ts
import { createSceneStack, type Scene } from "@karni/game/scenes";

const title: Scene = {
  name: "title",
  update: ({ services, stack }) => {
    if (services.input?.pressed("jump")) stack.replace(play, { duration: 0.3 });
  },
};
const stack = createSceneStack({ services: { loop, input, audio } });
stack.push(title);
// the loop's update calls stack.update(dt), its render calls stack.draw(alpha)
```

See [Scenes](https://cbsshekhawat18-lab.github.io/karni/game-scenes/).

## Game UI

`@karni/game/ui` is a DOM layer above the canvas, so the browser lays out the text, moves the
focus and reads it aloud. It has settings (volume sliders, mute, reduced motion, a colour-safe
palette switch, key remapping on the input), a pause menu wired to the loop, dialogs and confirm,
toasts, touch buttons that press the input's actions, a boot failure screen with Try again, a dev
overlay that shows only in development, and one strings table so every word can be replaced.

```ts
import { applySettings, createSettings, createUi, openPause, openSettings } from "@karni/game/ui";

const ui = createUi({ input });
const settings = createSettings({ storage });
applySettings({ store: settings, audio, input, ui });
openPause(ui, { loop, onSettings: () => openSettings(ui, { store: settings }) });
```

See [Game UI](https://cbsshekhawat18-lab.github.io/karni/game-ui/).

## Drawing and collision

For a game on plain canvas, two entry points cover what such games write by hand before their own
rules. Both are Canvas 2D and plain numbers only: no WebGL, no scene graph beyond layers, no entity
system and no rigid-body physics. A game that outgrows them moves to an engine adapter.

```ts
import { createCamera, createParticles, createRenderer, textStyle } from "@karni/game/draw";
import { createMove, moveBox } from "@karni/game/collide";

const camera = createCamera({
  view,
  bounds: { x: 0, y: 0, w: 1600, h: 540 },
  deadZone: { w: 60, h: 50 },
});
camera.follow(player);
const renderer = createRenderer({
  canvas,
  view,
  camera,
  layers: [{ name: "hills", parallax: 0.35 }, "world", "effects", { name: "hud", screen: true }],
});
renderer.on("world", (g) => g.sprite(hero.sprite, player.x, player.y, player.facing, 1));

const moved = createMove();
moveBox(player, dx, player.vy * dt, level.solids, undefined, moved);
player.grounded = moved.bottom;
```

- **Drawing** (`@karni/game/draw`). `createRenderer` draws layers in order (world layers through
  the camera with parallax, screen layers in game units), culls what is off screen and keeps the
  drawing in the game area. The painter draws shapes, text in a style that measures each string
  once, and sprites cut from sheets (`sheetFrames`, `defineClips`, `createAnimator`).
  `createCamera` follows with a dead zone and smoothing, stays in bounds, shakes and zooms.
  `createTweens` moves number properties with an easing, `createParticles` keeps its particles in
  a pool, and `createPool` is that pool for anything else. Shake and particles scale down under
  reduced motion.
- **Time scale and hit-stop** are on the loop: `loop.timeScale` and `loop.hitStop(ms)`.
- **Collision** (`@karni/game/collide`). Overlap and contact tests for boxes and circles, segment
  and sweep tests, `castRay`, `moveBox` (slides against solid boxes, one-way ledges, never passes
  through a thin solid) and `createTriggers` (enter, stay and exit per zone).

The per-frame paths make no garbage, a browser benchmark holds a frame budget with 2000 sprites
and 1500 particles, and each entry point has a gzip size budget checked by a test.

## Assets

`@karni/game/assets` loads a game's files in named groups with progress, retries and a readable
failure, and unloads a group to free its memory. With the Vite preset the `assets/` folder is the
manifest, PNG and JPEG files get a WebP copy (with `sharp` installed), and each group has a size
budget that `karni-game check` enforces.

```ts
import { createAssets } from "@karni/game/assets";
import { manifest, assetHosts } from "virtual:karni-game/assets";

const assets = createAssets({ manifest, audio, allowHosts: assetHosts });
await assets.load("core", { onProgress: ({ fraction }) => bar.set(fraction) });
context.drawImage(assets.image("core", "hero").source, 0, 0);
assets.unload("core");
```

See [Assets](https://cbsshekhawat18-lab.github.io/karni/game-assets/).

## Sound

`@karni/game/sfx` makes sounds from a few numbers (tones, sweeps, noise, envelopes, arpeggios), plays
them on the audio layer's buses with pitch and volume variation and a voice limit, and plays music
with a crossfade and ducking. It is silent until the first gesture and holds still while paused.

```ts
import { createSfx, presets } from "@karni/game/sfx";

const sfx = createSfx({ audio });
sfx.define("jump", presets.jump());
sfx.play("jump", { pitchVariation: 0.06 });
```

See [Sound](https://cbsshekhawat18-lab.github.io/karni/game-sound/).

## Building for portals

```ts
// vite.config.ts
import { defineConfig } from "vite";
import { karniGame } from "@karni/game/vite";

export default defineConfig({ plugins: [karniGame()] });
```

The preset sets a relative base, gives `virtual:karni-game/portal` the one adapter of the build,
puts that portal's SDK tag in the page and sets `__KARNI_GAME_DEV__` (true in `vite dev` only).
`singleFile: true` puts everything into index.html for `file://` and sandboxed frames.
`devBase: "/play/block-hopper/"` serves `vite dev` at the path the project serves the build at
(a game-first Karni project's `/play/<slug>/`), while a build keeps the relative base.

```bash
KARNI_GAME_GAMEDISTRIBUTION_GAME_ID=... npx karni-game package
```

builds a package per row of the portal table into `dist-portals/`, checks each one (hosts, other
portals' SDKs, localhost and plain-http addresses, secret-shaped tokens, debug hooks and console
calls, the size budget) and zips it when the row says. `karni-game check-source` looks for portal
ids typed into code. `definePortals` changes a row or adds a portal of the project's own.

## Escape hatches

Every piece takes its collaborators as options: the adapter of a portal Karni does not list, the
frame scheduler and clock of the loop, the AudioContext, the storage backend, the transport and
conflict rule of the data client, the build function of the packaging step and the browser of the
smoke harness. The painter hands out the raw 2D context in the layer's units, the camera and the
particles take their own random source, and the box mover takes a broad phase of the game's own.
Each module also works alone.

## License

Apache-2.0. @karni/game is released with every other Karni package, at one version.
