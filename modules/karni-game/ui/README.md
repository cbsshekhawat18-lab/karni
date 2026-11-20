# @karni/game

The browser side of the Karni game add-on: portal and ad adapters, a canvas loop, input, audio,
local saves, a seeded random generator, an offline-first data client and per-portal builds.
Experimental.

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
| `@karni/game/vite`                                          | `karniGame()`, the Vite preset                                                                        |
| `@karni/game/build`                                         | the portal table, the package checks, `packagePortals`, `zipFolder`                                   |
| `@karni/game/phaser`, `@karni/game/pixi`, `@karni/game/r3f` | the engine adapters                                                                                   |
| `@karni/game/smoke`                                         | `runSmoke`, the browser smoke harness                                                                 |
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
and a rewarded continue), and the browser tests play it.

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
smoke harness. Each module also works alone.

## License

Apache-2.0. @karni/game is released with every other Karni package, at one version.
