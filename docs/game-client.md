---
description: "@karni/game (experimental): the browser side of the Karni game add-on. Portal and ad adapters, a canvas loop with a fixed step, input, audio, local saves with migrations, a seeded random generator, an offline-first data client, per-portal builds with checks, engine adapters and a browser smoke harness."
---

# Games in the browser (@karni/game)

!!! warning "Experimental"
    `@karni/game` is [experimental](stability.md#experimental-names): a name or
    an option may change in a minor release, with a CHANGELOG entry.

`@karni/game` is the npm package of the game add-on. It holds what every web
game rebuilds: the portal and ad layer, the frame loop, input, audio, the save
layer, a seeded random generator, a client for the game server, the
per-portal build and a browser test. A game writes its own rules and drawing
only.

It runs with no server. Saves, boards, a wallet, achievements and a daily
seed then live on the device, by the same rules the server keeps. With the
[karni-game module](game.md) on the project's server, the same calls go to the server,
and writes made offline wait in a queue. The server is an upgrade, not a
requirement.

The core has no runtime dependency. Every export is tree-shaken, so a game
that imports only `createRng` bundles only the generator. The package is
ESM.

```bash
npm install @karni/game
```

## Entry points

| Import | For |
|---|---|
| `@karni/game` | the game in the browser: portal, loop, view, input, audio, saves, random, data client |
| `@karni/game/portals/<name>` | one portal adapter (`none`, `fake`, `poki`, `crazygames`, `gamedistribution`, `y8`) |
| `@karni/game/vite` | `karniGame()`, the Vite preset |
| `@karni/game/build` | Node: the portal table, the package and source checks, `packagePortals`, `zipFolder` |
| `@karni/game/phaser`, `@karni/game/pixi`, `@karni/game/r3f` | the engine adapters |
| `@karni/game/sim` | the simulation contract, recorder, replay, state hash and test kit ([Simulation and replay](game-sim.md)) |
| `@karni/game/scenes` | the scene stack, overlays, transitions, the entity list and the store ([Scenes](game-scenes.md)) |
| `@karni/game/ui` | the DOM UI kit: settings, pause, dialogs, toasts, touch buttons, the boot failure screen, the dev overlay ([Game UI](game-ui.md)) |
| `@karni/game/smoke` | Node: `runSmoke`, the browser smoke harness (needs Playwright) |
| `@karni/game/client` | types for `virtual:karni-game/portal`, `__KARNI_GAME_DEV__` and `__KARNI_GAME_PORTAL__` |

## Portal and ads

A game on a web game portal calls the portal's SDK: loading and gameplay
events, interstitials, rewarded ads, the player's mute setting. Each SDK has
its own names, and each fails in its own way (an ad blocker, a slow network,
another domain). `createPortal(adapter, options)` wraps one adapter in the
rules every game needs:

- `init()` waits at most `initTimeoutMs` (5000) and resolves false without
  the SDK, so the game boots anyway. An SDK that comes up later is used from
  then on.
- Calls made before the SDK is ready are replayed when it is.
  `gameplayStart` and `gameplayStop` are sent in pairs, and gameplay stops
  for every ad and starts again after it.
- `interstitial()` keeps `interstitialCooldownMs` (60000) between ads that
  played, and `firstInterstitialAfterMs` after start. It reports `shown`,
  `skipped`, `cooldown`, `busy`, `unavailable` or `error`.
- `rewarded()` resolves true only on the SDK's completed event. A dismissed,
  failed, unfilled or timed-out ad gives nothing. A completed one restarts
  the interstitial cooldown (`rewardedResetsCooldown`).
- An ad that never ends is given up after `adTimeoutMs` (90000).
- Every SDK call that throws is reported on the `error` event, never to the
  game.

`linkPortal(portal, { audio, loop, input })` mutes the ad and portal sources
of the audio, pauses the loop for each ad and portal pause, and lets go of
held keys when an ad starts. With no SDK (`noPortal()`) every call is a no-op
and an ad call reports `unavailable`.

| Portal | Adapter | From the project's config | SDK |
|---|---|---|---|
| `web`, `itch` | `noPortal` | nothing | none |
| `poki` | `poki()` | nothing | the tag in the page |
| `crazygames` | `crazyGames()` | nothing | the tag in the page, the site's mute setting, the data module as storage |
| `gamedistribution` | `gameDistribution()` | `gameId` | loaded by the adapter after `GD_OPTIONS` is set |
| `y8` | `y8()` | `appId`, and `gameId` for ads | the tag in the page |

A portal's ids are never in the source. They come from the project's config
(`karniGame({ config: { y8: { appId } } })`) or the build environment
(`KARNI_GAME_Y8_APP_ID`), and a build that misses a required one stops with
the variable's name. `fakePortal()` plays ads that end as its options say,
for development (`karniGame({ devPortal: "fake" })`) and tests. A portal
Karni does not list is an adapter of the project's own: an object with `name`
and `init`, and any of the other calls.

## The loop, the view and pauses

These helpers are for a game on plain canvas. An engine (Phaser, PixiJS,
React Three Fiber) keeps its own loop: see [engines](#engines).

```ts
const loop = createLoop({
  step: 1 / 120,
  update: (dt) => world.step(dt),
  render: (alpha) => draw(alpha),
  afterFrame: () => input.endFrame(),
});
pauseOnHidden([loop, audio]);
loop.start();
```

- `createLoop` clamps the frame time to `maxDt` (0.05 s), runs `update` in
  fixed steps when `step` is set, at most `maxSteps` (5) a frame, and drops a
  longer backlog so a slow device slows the game instead of freezing it. A
  frame that throws is reported (`onError`, the console by default) and the
  loop runs on.
- Pauses have reasons: `pause("menu")`, `pause("ad")`. The loop runs again
  when every reason is lifted, so an ad ending never unpauses a game the
  player paused. `createPauseReasons` gives the same to any target.
- `pauseOnHidden(targets, { blur })` pauses on a hidden tab ("hidden") and on
  a window without focus ("blur").
- `createFixedStep({ step, maxSteps })` is the accumulator alone, for a loop
  of another kind.
- `createView({ canvas, width, height })` sizes the canvas's backing store to
  its CSS size times the device pixel ratio, capped at `maxDpr` (2) and
  `touchMaxDpr` (1.5) on touch devices. With a virtual resolution it fits it
  inside (`fit: "letterbox"`, or `"cover"`), `apply(context)` sets the
  transform, and `toGame(clientX, clientY)` maps a pointer into game units.

## Input

```ts
const input = createInput({
  target: canvas,
  view,
  bindings: { left: ["ArrowLeft", "KeyA", STICK.left], jump: ["Space", POINTER] },
});
if (input.pressed("jump")) jump();
```

`held`, `pressed` and `released` take an action or a key code
(`KeyboardEvent.code`, or `POINTER` for the primary mouse button, finger or
pen). Pressed and released last one frame, and a tap shorter than a frame
still reads as pressed. With a fixed step, the loop calls `afterFrame` only
after a frame that ran a step (or while paused), so a press made in a frame
with no step reaches the next one: on a 120 Hz screen with a step of 1/60,
every other frame has none. Space and the arrow keys do not scroll the page,
keys typed into a text field are ignored, and everything is let go on blur.
`onFirstGesture(callback)` runs inside the player's first tap or key, which
is where browsers let audio start. `press` and `release` drive codes by hand
(on-screen buttons, tests).

`createVirtualStick(input, options)` is a floating stick for touch screens:
it appears under the thumb in its zone (the left half by default), reports a
deflection and presses `STICK.left`, `right`, `up` and `down`, so one set of
bindings serves the keyboard and the touch screen.

## Audio

`createAudio()` is a small Web Audio graph with master, music and effects
volumes. `unlockOn(input)` starts it on the first gesture. Three mute
sources are kept apart: `player` (the game's own setting), `ad` and `portal`
(the portal's setting), so an ad ending never unmutes a player who muted.
`pause(reason)` and `resume(reason)` suspend the context, and
`follow(loop)` pauses audio with the loop. `load(url)` resolves null for a
file that cannot be had, `play(buffer)` returns null before unlock, and
music asked for before unlock starts on unlock.

## Saves on the device

```ts
// After `await portal.init()`, so the portal's data module is there.
const storage = createStorage({ namespace: "block-hopper", portal: portal.storage() });
const save = createSave({
  storage,
  version: 2,
  defaults: () => ({ best: 0, plays: 0 }),
  migrations: { 1: (old) => ({ best: (old as { high: number }).high, plays: 0 }) },
});
const { data, status } = save.load();
```

- `createStorage` probes the browser's storage and falls back to memory where
  it is blocked (sandboxed frames, privacy modes), so a boot never fails on
  storage. Keys are namespaced. A portal's data module, when given, is read
  first and written with the local copy.
- `createSave` stores `{ v, savedAt, data }`. `migrations[n]` turns version n
  into n + 1, and `migrations[0]` adopts a save written before versioning.
  `validate` cleans loaded data. By default an object is merged over the
  defaults, so a field added later gets its default.
- A save that does not parse, fails a migration or fails `validate` loads as
  `corrupt`: the game gets the defaults and the bad copy is kept under
  `save.backup.<time>` (the last three). A save written by a newer build
  loads as `newer`, kept the same way.

## Random numbers and the daily seed

`createRng(seed)` is a seeded generator (mulberry32): `next`, `int`, `float`,
`chance`, `pick`, `shuffle`, `fork(label)` for separate streams, and a state
to resume a sequence. A text seed is hashed (`hashSeed`). `dayKey(date,
timeZone)` names a day and `dateSeed(day, salt)` gives the same seed on every
device. The data client's `daily()` gives the server's date and seed when
the server answers. Offline it gives the server's seed for today when it has
one, and otherwise `deviceDailySeed`, marked `source: "device"`: the device's
clock can be changed, so that seed suits practice, not the shared board.

## The data client

`createGameClient({ game, storage, server })` speaks the karni-game HTTP
contract ([the game API](game-api.md)). Without `server` the same calls run on the device.

| Call | With a server | Without one |
|---|---|---|
| `boot()`, `config(key, fallback)`, `flag(key)` | the game's config, flags and clock, cached for offline | the bundled `defaults` |
| `signInGuest(handle)` | a server-issued guest token, asked for with an intent | a device guest, which joins the server when it can |
| `upgrade()` | the guest's progress joins the account the player signed in to | not available |
| `saves.write(slot, data, schemaVersion)`, `saves.load(slot)` | kept on the device at once, sent with the version it was based on | the device |
| `submitScore(board, value, { run, playedAt })`, `leaderboard`, `around` | the server's boards (a run carries a seed and an input log, a score when it was played) | the device's board per period |
| `wallet`, `ledger`, `shop`, `buy`, `equip`, `unequip` | the server's wallet: only the server changes a balance | the device's wallet by the declared `local` setup |
| `rewards`, `adReward`, `claimReward`, `rewardIntent` | rewards the server declares, each with its `trust` | the device's ad and daily rewards |
| `daily`, `checkIn` | the server's date, seed and streak | the device's |
| `progress(events)`, `achievements`, `missions` | counters the server turns into unlocks | the device's counters and achievements |
| `track(name, props)` | batched, the events the game declares | the `analyticsSink` only |
| `multiplayerToken()` | a short-lived token for a realtime server of the project's own | not available |

Writes that change a score, progress or analytics are sent at once when
nothing waits before them, or go to the queue. The queue is kept in the
game's storage, sends in order with each write's intent (so a retry never
counts twice), backs off after a failure, waits as long as a rate limit
asks, and drops a write the server refuses for good (the `rejected` event).
The latest save of a slot replaces a waiting one. `sync()` sends what waits,
and the client also tries when the browser comes online and every
`syncEveryMs` (30000).

Every write is safe to send twice:

- A guest is asked for with an intent, kept with its body until the answer
  arrives. A lost answer gives the same guest on the next try (with a new
  token), never a second one.
- An analytics batch carries its intent, so a retried batch is published
  once.
- A score carries `played_at`, when it was played on the server's clock (the
  device's, corrected by the server's last answer). A score played offline
  before midnight is on that day's boards when it reaches the server the
  next morning. When the server does not trust the time (`GAME036`: older
  than `KARNI_GAME_PLAYED_AT_WINDOW`, or a device clock ahead of it), the
  score is sent again without it and counts as played now.

A slot the server says is empty (`404 GAME037`, a save deleted on another
device) is forgotten on this device too, unless this device changed it. A
`404` without a code is a path the server does not have (the API mounted
elsewhere), and the device's copy is kept.

A save changed here and on the server (`409 GAME008`) is settled by
`onConflict(local, server)`: return `"local"`, `"server"` or merged data.
The default keeps the server's copy and keeps this device's under
`slot.<name>.conflict`, so nothing is lost. The `conflict` event says what
happened.

A project that signs people in through Karni passes `@karni/ui`'s client as
the transport, so every call carries the account:

```ts
const client = createGameClient({
  game: "block-hopper",
  storage,
  server: { transport: karniClient, signedIn: () => auth.user !== null },
});
```

Without `@karni/ui`, the built-in transport takes `baseUrl`,
`getAccessToken` (a JWT) or `getHeaders: csrfHeader` (a session cookie on the
same site).

A game built for a portal runs on the portal's domain and calls the game
API on the project's. Its build names the API (`KARNI_GAME_API_URL`, or
`karniGame({ apiUrl })`), the game reads it as `gameApiUrl` and passes it to
the built-in transport:

```ts
import { createPortalAdapter, gameApiUrl } from "virtual:karni-game/portal";

const client = createGameClient({
  game: "block-hopper",
  storage,
  server: gameApiUrl
    ? { baseUrl: gameApiUrl } // a portal build: the guest's token, or getAccessToken (a JWT)
    : { transport: karniClient, signedIn: () => auth.user !== null },
});
```

The server lists the portal's origin in `KARNI_GAME_CORS_ORIGINS` and lets
the browser send the token's header
([from another origin](game.md#players-a-guest-first-an-account-later)). Such
a call signs in with a token only, the guest's `X-Player-Token` or an
account's JWT: a session cookie never crosses origins.

The server owns the truth. The client never sends a coin amount, an unlock
or a reward: it reports what happened, and the server decides. `grant()`
exists only without a server, and the device's balances never reach one.

An ad reward is played by its `trust` (who vouches that the ad was watched):

```ts
const result = await client.adReward("ad-coins", (intent) => portal.rewarded());
// "granted" (with the new balance), "pending", "not-watched" or "unavailable"
```

With `trust: "client"` the reward is claimed once the ad was watched to the
end. With `trust: "callback"` the client first asks for the reward's intent
and passes it to `show`, which hands it to the portal's ad call. The
portal's server then calls the game API back, signed, and the server grants
the reward: the result is `"pending"`, and the wallet shows it a moment
later. Without a server every ad reward is the device's own.

## Building for portals

```ts
// vite.config.ts
import { defineConfig } from "vite";
import { karniGame } from "@karni/game/vite";

export default defineConfig({ plugins: [karniGame({ devPortal: "fake" })] });
```

```ts
// the game
import { createPortalAdapter } from "virtual:karni-game/portal";
const portal = createPortal(createPortalAdapter());
```

The preset sets the relative base (`./`) a zip and an iframe need, makes
`virtual:karni-game/portal` export the build's one adapter, puts that
portal's SDK tag in the page, and defines `__KARNI_GAME_DEV__` (true only in
`vite dev`) and `__KARNI_GAME_PORTAL__`. Guard debug hooks with
`__KARNI_GAME_DEV__` so builds drop them. `singleFile: true` puts the scripts
and styles inside index.html, for `file://` and sandboxed frames. The portal
comes from `portal`, else `KARNI_GAME_PORTAL`, else `web`.

`karni-game package` (or `packagePortals()`) builds one package per row of
the portal table into `dist-portals/<portal>/`, checks it and zips it when
the row says. `karni-game check <dir> --portal <name>` checks a package
alone. `--api-url` (or `KARNI_GAME_API_URL`) names the game API the packages
call, and its host is allowed. `--allow-host` allows another (a font host). A
check fails the package for:

- No index.html at its root, or a path from the site's root (`/assets/...`).
- A host that is not the portal's own SDK host or the game API's, a
  localhost or plain-http address.
- Another portal's SDK (one SDK per build) or the row's forbidden patterns
  (a Poki build must not turn on the SDK's debug mode).
- A secret-shaped token (a private key, a live payment key, a cloud access
  key, a secret assigned in code).
- A `window.__` global, a `debugger` statement or a `console.log` left in.
- A size over the row's budget (20 MiB unless the row or the project sets
  another).

`karni-game check-source` looks for portal ids typed into code, and for the
values of `KARNI_GAME_*` variables anywhere in the source. `definePortals`
changes a row (a budget, an allowed host) or adds a portal with an adapter
of the project's own.

## Engines

A game on an engine keeps the engine's loop, input, scale and scenes. The
adapters connect the rest. None of them imports the engine, so each works
with the version the game uses.

- **Phaser** (`connectPhaser(game, { portal, client })`): the portal, the
  client and the link go into the game's registry for every scene
  (`this.registry.get(KARNI_REGISTRY.portal)`). The loop sleeps and the sound
  is muted for ads and portal pauses, the loop sleeps on blur, and
  `setMuted("player", ...)` keeps the player's mute apart.
- **PixiJS** (`connectPixi(app, { step, update, portal, audio })`): Pixi's
  ticker stays the loop, with an optional fixed step on it, and stops for a
  hidden tab, blur, ads and portal pauses.
- **React Three Fiber** (`@karni/game/r3f`): `KarniGameProvider` and
  `useKarniGame` share the services, `useFixedStep(update)` steps inside
  `useFrame`, `useEndInputFrame(input, fixed)` clears input edges after each
  frame that ran a step,
  `useGamePause` stops the Canvas's frame loop for ads and hidden tabs, and
  `usePortalState` gives the portal's state to React. It needs React and
  `@react-three/fiber`.

## Testing a game

Keep the rules in `src/rules/` on the contract of `@karni/game/sim`, as the
example's `example/block-hopper/src/rules/` does: a test then plays the game
headless, and a seed plus the input log replays a run exactly. The page
[Simulation and replay](game-sim.md) has the contract, the recorder, the
determinism and fuzz helpers and the purity check
(`karni-game check-rules`).

`runSmoke(options)` from `@karni/game/smoke` tests the built game in
headless Chromium:

```ts
const result = await runSmoke({
  dir: "dist",
  seconds: 4,
  script: [{ at: 200, key: "Space" }, { at: 400, key: "ArrowLeft", action: "down" }],
});
expect(result.problems).toEqual([]);
```

It serves the folder on a free port, plays with the scripted keys and taps
(`touch: true` emulates a phone), fails on a console error, a page error or
a failed request, checks that the canvas changed, then boots again with
every stored value broken and plays again. `check(page, phase)` adds the
game's own assertions. It needs Playwright and its Chromium.

## The example game

`modules/karni-game/ui/example/block-hopper/` is Block Hopper, a small
platformer on every piece: move, jump, coins, a score, a versioned save with
a migration, a leaderboard, a rewarded continue, the touch stick and a
procedural sound. `npm run example:dev` plays it with the fake portal, and
`npm run test:smoke` builds it and plays it in a headless browser over http,
by touch, and as a single file from `file://`.

## What it does not do

- It runs no realtime server: [the karni-game module](game.md#multiplayer-a-realtime-server-of-your-own) issues the token a
  realtime server of the project's own verifies.
- It has no scene system, physics, asset loader, procedural music, service
  worker or quality tiers. Engines bring their own, and most of these are
  the game's own business.
- The device's rules without a server are for play, not trust: a player can
  edit local storage. Shared boards and balances need the server.
