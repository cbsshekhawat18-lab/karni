---
description: "Simulation and replay in @karni/game/sim (experimental): write a game's rules as pure state and a step over fixed ticks, record a run as a seed and inputs, replay it, hash the state, send the run with a score, and test the rules with determinism, fuzz and purity checks."
---

# Simulation and replay (@karni/game/sim)

!!! warning "Experimental"
    `@karni/game/sim` is [experimental](stability.md#experimental-names): a name
    or an option may change in a minor release, with a CHANGELOG entry.

`@karni/game/sim` is the contract for a game's rules. The rules are a pure
function of a seed and the player's inputs: plain state, one `step` per fixed
tick, inputs as data and a seeded random generator. Nothing in them reads a
clock, the page or the network. From that one rule you get:

- a headless test of the whole game, with no page,
- a recording of a run (the seed and the inputs that changed),
- a replay that reaches the same state, and a state hash to check it,
- a run you can send with a score,
- the same rules in the browser, in Node and in a test.

The entry point has no dependency and no Node API, so it runs in the browser
and in Node, and a game bundles only what it imports.

```ts
import { createSim, defineSim } from "@karni/game/sim";
```

## The rules

```ts
import { defineSim } from "@karni/game/sim";

interface Run { x: number; vy: number; grounded: boolean; coins: number }
interface Input { right: boolean; jump: boolean }

export const hopper = defineSim<Run, Input, "jump" | "coin">({
  dt: 1 / 120,                                  // seconds per tick (default 1/60)
  idle: { right: false, jump: false },          // the input of a tick with no input
  init: (ctx) => ({ x: 0, vy: 0, grounded: true, coins: ctx.rng.int(0, 2) }),
  step(run, input, ctx) {
    run.x += (input.right ? 200 : 0) * ctx.dt;  // time is ctx.dt, never a clock
    if (input.jump && run.grounded) {
      run.vy = -640;
      run.grounded = false;
      ctx.emit("jump");                         // events are for sound and effects
    }
  },
  done: (run) => run.x > 5000,
  score: (run) => Math.floor(run.x / 10) + run.coins * 10,
  invariants: { "x is finite": (run) => Number.isFinite(run.x) },
  randomInput: (rng) => ({ right: rng.chance(0.7), jump: rng.chance(0.05) }),
});
```

| Part | Rule |
|---|---|
| State | Plain data: objects, arrays, numbers, strings, booleans, null. No class instances, `Map`, `Set`, `Date` or functions, because the state is hashed and kept. A step returns nothing and changes the state in place, or returns the next state. |
| `step(state, input, ctx)` | Runs once per tick. `ctx.dt` is the tick length, `ctx.tick` the tick number, `ctx.rng` a seeded generator, `ctx.stream(label)` a separate seeded generator per system, `ctx.emit(event)` reports something that happened. |
| `init(ctx, config)` | The state at tick 0. It draws from `ctx` too, so a run's world comes from its seed. `config` is any plain data a run needs (a level, a difficulty) and is part of the recording. |
| Input | Plain data, one value per tick. Say it as the state of the controls (`{ left, right, jump }`), and make a press an edge in the input (`jump` is true for the tick it went down). |
| `done`, `score` | The rules say when a run is over and what it scored. The driver decides what to do about it. |
| `invariants` | Facts that hold after every tick. A function returns true, or false, or a text saying why not. |
| Things outside the rules | A rewarded continue, a revive or a pause that changes the world is an input (`revive: true`), so a run that used it still replays. |

Every random number comes from `ctx.rng` or `ctx.stream(label)`. They are the
generator of `createRng` (`@karni/game`), and their state is part of the hash.
Use one stream per system (`ctx.stream("platforms")`) so adding a draw in one
system does not move another.

## Running, recording and replaying

```ts
import { createRecorder, replay, verify } from "@karni/game/sim";

const recorder = createRecorder(hopper, { seed: 20261119, build: "1.4.0" });
recorder.step({ right: true, jump: false });   // one tick; returns the tick's events
recorder.step({ right: true, jump: true });
const recording = recorder.finish();           // { seed, ticks, inputs, hash, score, ... }

const again = replay(hopper, recording);       // the sim at the end of the recording
again.hash() === recording.hash;               // true
verify(hopper, recording);                     // { ok: true, expected, actual, ... }
```

- `createSim(definition, { seed, config })` is a run with no recording:
  `sim.step(input)`, `sim.state`, `sim.tick`, `sim.score`, `sim.done`,
  `sim.hash()` and `sim.failedInvariants()`.
- `createRecorder` wraps a sim and keeps the seed, the config and the ticks
  where the input changed (`inputs: [[tick, input], ...]`, from the idle
  input). A long run with few input changes is a short list.
- `replay(definition, recording, { until, onTick })` runs a recording again.
  `onTick` sees each tick's sim and events, to draw a ghost or a watch-again.
- `verify(definition, recording)` replays and checks the hash and the score.
  It never throws: a rule that throws, or a recording made with another `dt`,
  is a verdict with `ok: false` and a `reason`.

The sim does not stop at `done`. A driver that wants to stop checks
`sim.done`, and a game with a continue keeps stepping.

## The state hash

`sim.hash()` is 16 hex digits over the tick count, every random stream's state
and the state (or `snapshot(state)` when the rules give one, to leave out a
cache). The state is written as canonical text first: keys sorted, numbers as
the language's shortest round-trip text, `-0` as `0`. The same state gives the
same hash on every machine and engine. `hashState(value)` and `canonical(value)`
are exported for the game's own use.

The hash detects a change. It is not a signature, and a player can compute it
for a run they made up.

Floating-point is exact for `+`, `-`, `*`, `/` and `Math.sqrt` on every engine.
The language allows `Math.sin`, `Math.cos`, `Math.exp`, `Math.pow` and the like
to differ in the last digit between engines. If the replay must match across
browsers and Node, keep them out of the rules, or round their result.

## A run on the server

The score API's `run` is `{ seed, inputs, duration_ms, build, meta }`
([the game API](game-api.md#scores-and-boards)). A recording fits it
without any change on the server:

```ts
import { toRunRecord, fromRunRecord } from "@karni/game/sim";

await client.submitScore("high", sim.score, { run: toRunRecord(recorder.finish()) });
```

| Run field | From the recording |
|---|---|
| `seed` | the seed as text |
| `inputs` | `[tick, input as JSON text]` for each tick where the input changed. The first number is a tick, not milliseconds |
| `duration_ms` | `ticks * dt * 1000` |
| `build` | the recording's `build` |
| `meta` | the recording's `meta`, plus `karni_sim` (the format), `seed_kind`, `dt`, `ticks`, `hash`, `score` and the `config` |

The server keeps the run and shows it to staff, within
`KARNI_GAME_MAX_RUN_BYTES`. It does not replay it today and it adds nothing
for the recorder. `fromRunRecord(run)` reads a stored run back into a
recording, and `verify(rules, recording)` in a script or a test says whether it
reaches its hash. A daily board still takes the day's seed from the server:
start the recorder with `client.daily()`'s seed.

## Driving the loop

`createSimLoop` makes the loop's fixed step the sim's `dt` and runs one tick per
step:

```ts
import { createSimLoop } from "@karni/game/sim";

const loop = createSimLoop({
  target: () => recorder,                       // a function, so a new run needs no new loop
  input: () => ({ right: input.held("right"), jump: input.pressed("jump") }),
  active: () => screen === "play",
  beforeStep: () => { /* menus, mute keys */ },
  onEvents: (events) => events.forEach(playSound),
  render: (alpha) => draw(recorder.sim.state, alpha),
  afterFrame: () => input.endFrame(),
});
loop.start();
```

The loop's own options (`maxDt`, `maxSteps`, `renderWhilePaused`, `onError`, the
frame scheduler) pass through. `active` is read before `beforeStep`, so a screen
change made there takes effect on the next step. The sim's `dt` must not change
while the loop runs.

`example/block-hopper/` in the package is the proof: its rules are in
`src/rules/` on this contract, its page drives them with `createSimLoop`, and
its run goes to the board through `toRunRecord`.

## Testing the rules

```ts
import { checkDeterminism, fuzz, runHeadless, verify } from "@karni/game/sim";

it("keeps the score of a known seed", () => {
  const run = runHeadless(hopper, { seed: 42, ticks: 6000, input: bot });
  expect(run.score).toBe(231);
  expect(verify(hopper, run.recording).ok).toBe(true);
});

it("is deterministic", () => {
  checkDeterminism(hopper, { seed: 9, ticks: 800, input: bot });
});

it("survives random input", () => {
  fuzz(hopper, { seed: 5, runs: 12, ticks: 1500 });
});
```

- `runHeadless(definition, { seed, ticks, input })` runs up to N ticks of
  scripted input: a list (one per tick, then idle) or a function of
  `(tick, sim)`, which is how a bot reads the state. It returns the sim, the
  recording, every event, the score and the hash. It stops at `done` unless
  `stopWhenDone: false`.
- `checkDeterminism` runs the same seed and inputs twice, then replays the
  recording, and compares the hash tick by tick (`every` thins them). It throws a
  `SimTestError` naming the first tick that differs. It catches a clock,
  `Math.random`, state kept outside the sim and a step that depends on object
  identity.
- `fuzz` gives each of N runs its own seed and random inputs (from the rules'
  `randomInput`, or the `input` option) for N ticks. It fails on a throw, a NaN
  or infinite number, state that is not plain data, and any invariant the rules
  declare. The `FuzzFailure` carries the `seed`, the `tick` and a `recording`
  that replays up to the failure, to keep as a regression test.

These helpers throw plain errors, so they work in any test runner.

## The purity check

A game keeps its rules in `src/rules/`. The check fails on a clock (`Date`,
`performance`), outside randomness (`Math.random`, `crypto`), the page
(`document`, `window`, `navigator`, storage, `requestAnimationFrame`,
audio and canvas types), the network (`fetch`, `XMLHttpRequest`, `WebSocket`,
`EventSource`, `Worker`) and timers (`setTimeout`, `setInterval`). Comments and
strings are not read as code. Test files (`*.test.*`, `*.spec.*`) are skipped.

```bash
npx karni-game check-rules            # src/rules
npx karni-game check-rules path/to/rules
```

```ts
import { checkRules } from "@karni/game/build";   // Node
expect(checkRules("src/rules")).toEqual([]);

import { findImpurities } from "@karni/game/sim"; // text in, any runtime
```

A use that must stay carries a marker with a reason, on its line or the line
above. A marker names its rules (`clock`, `random`, `dom`, `network`, `timer`),
joined by commas with no space, and a marker with no reason fails too:

```ts
// karni-allow: clock the build stamp is shown on the title, never read by a step
const built = Date.now();
```

A rules folder that does not exist fails the check, so a renamed folder cannot
pass by being empty.

## Escape hatches

- `snapshot(state)` chooses what is hashed. `step` may return a new state.
- `ctx.stream(label)` gives as many random streams as the rules need.
- `createSimLoop` takes any `SimTarget` (a `step(input)` and a `dt`), and every
  loop option. The sim does not need the loop: call `sim.step` from any driver.
- `toRunRecord` and `fromRunRecord` are plain functions. A game with its own run
  format uses the recording directly.
- A game on an engine (Phaser, PixiJS, React Three Fiber) steps the sim from the
  engine's own fixed update. The sim touches no renderer.
- A game that cannot be pure keeps the impure part outside `src/rules/` and
  passes it in as input or config.

## What it does not do

- It does not draw, collide or load assets. Those are other entry points.
- It does not replay a run on the server. The server stores the run, and a script
  can verify it with the same rules.
- It does not sync a match between players. The state hash is the check a future
  match service can use.
- It does not make a game fair. A player can send a run they made up, and the
  hash does not prove otherwise: the server's range checks and review still decide.
