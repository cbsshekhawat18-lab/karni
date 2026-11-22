import { describe, expect, it, vi } from "vitest";
import {
  FuzzFailure,
  SimTestError,
  canonical,
  checkDeterminism,
  createRecorder,
  createSim,
  createSimLoop,
  defineSim,
  findNonFinite,
  fromRunRecord,
  fuzz,
  hashState,
  replay,
  runHeadless,
  toRunRecord,
  verify,
} from "../src/sim";

interface Counter {
  n: number;
  luck: number;
  log: number[];
}
type CounterInput = { add: number };

/** A tiny game: add the input to a counter, roll a seeded die each tick. */
const counter = defineSim<Counter, CounterInput, string>({
  dt: 0.1,
  idle: { add: 0 },
  init: () => ({ n: 0, luck: 0, log: [] }),
  step(state, input, ctx) {
    state.n += input.add;
    state.luck += ctx.rng.int(1, 6);
    state.log.push(ctx.tick);
    if (state.n % 5 === 0 && input.add) ctx.emit("five");
  },
  done: (s) => s.n >= 100,
  score: (s) => s.n * 10 + s.luck,
  invariants: { "n is not negative": (s) => s.n >= 0 },
  randomInput: (rng) => ({ add: rng.int(0, 3) }),
});

describe("the state hash", () => {
  it("is the same text and hash on every machine: a fixed value gives a fixed result", () => {
    const value = { b: [1, 2.5, -0, null], a: "xé", c: { z: true, y: false } };
    expect(canonical(value)).toBe('{"a":"xé","b":[1,2.5,0,null],"c":{"y":false,"z":true}}');
    expect(hashState(value)).toBe("f3727bbd7ee17c00");
    expect(hashState({ a: 1, b: 2 })).toBe(hashState({ b: 2, a: 1 }));
  });

  it("tells apart values that differ", () => {
    expect(hashState({ a: 1 })).not.toBe(hashState({ a: 2 }));
    expect(hashState([1, 2])).not.toBe(hashState([2, 1]));
    expect(hashState({ a: "1" })).not.toBe(hashState({ a: 1 }));
    expect(hashState(Number.NaN)).not.toBe(hashState(null));
    expect(hashState(0.1 + 0.2)).not.toBe(hashState(0.3));
  });

  it("refuses state that is not plain data", () => {
    expect(() => hashState({ when: new Date(0) })).toThrow(/Date/);
    expect(() => hashState({ map: new Map() })).toThrow(/Map/);
    expect(() => hashState({ f: () => 1 })).toThrow(/function/);
    const loop: Record<string, unknown> = {};
    loop.self = loop;
    expect(() => hashState(loop)).toThrow(/itself/);
  });

  it("finds a number that is not finite", () => {
    expect(findNonFinite({ a: [1, { b: Number.NaN }] })).toBe("state.a[1].b is NaN");
    expect(findNonFinite({ a: 1 })).toBeNull();
  });
});

describe("a sim and its recorder", () => {
  it("runs the rules from the seed: same seed, same run", () => {
    const a = createSim(counter, { seed: 7 });
    const b = createSim(counter, { seed: 7 });
    const c = createSim(counter, { seed: 8 });
    for (let t = 0; t < 20; t += 1) {
      a.step({ add: 1 });
      b.step({ add: 1 });
      c.step({ add: 1 });
    }
    expect(a.hash()).toBe(b.hash());
    expect(a.hash()).not.toBe(c.hash());
    expect(a.state.n).toBe(20);
    expect(a.tick).toBe(20);
  });

  it("collects the events of each tick, and a step may return the next state", () => {
    const sim = createSim(counter, { seed: 1 });
    expect(sim.step({ add: 5 })).toEqual(["five"]);
    expect(sim.step({ add: 1 })).toEqual([]);
    const pure = defineSim<{ n: number }, number>({
      idle: 0,
      init: () => ({ n: 0 }),
      step: (state, input) => ({ n: state.n + input }),
    });
    const next = createSim(pure, { seed: 1 });
    next.step(2);
    expect(next.state).toEqual({ n: 2 });
    expect(next.score).toBe(0);
    expect(next.done).toBe(false);
  });

  it("puts every random stream into the hash", () => {
    const streams = defineSim<{ n: number }, null>({
      idle: null,
      init: () => ({ n: 0 }),
      step: (state, _input, ctx) => {
        state.n += ctx.stream("loot").int(0, 9);
      },
    });
    const a = createSim(streams, { seed: 1 });
    const b = createSim(streams, { seed: 1 });
    a.step();
    b.step();
    const before = a.hash();
    expect(before).toBe(b.hash());
    // A second draw moves the stream only on one side: the hashes part.
    b.step();
    expect(a.hash()).not.toBe(b.hash());
  });

  it("records only the ticks where the input changed", () => {
    const recorder = createRecorder(counter, { seed: 3, build: "1.2.0", meta: { level: "cave" } });
    const plan = [0, 0, 1, 1, 1, 0, 2, 2];
    for (const add of plan) recorder.step({ add });
    const recording = recorder.finish();
    expect(recording.inputs).toEqual([
      [2, { add: 1 }],
      [5, { add: 0 }],
      [6, { add: 2 }],
    ]);
    expect(recording).toMatchObject({
      v: 1,
      seed: 3,
      dt: 0.1,
      ticks: 8,
      build: "1.2.0",
      meta: { level: "cave" },
      score: recorder.sim.score,
      hash: recorder.sim.hash(),
    });
  });

  it("replays a recording to the same state, a part of it too", () => {
    const run = runHeadless(counter, { seed: 5, ticks: 30, input: (t) => ({ add: t % 3 }) });
    expect(replay(counter, run.recording).hash()).toBe(run.hash);
    const part = replay(counter, run.recording, { until: 10 });
    expect(part.tick).toBe(10);
    const seen: number[] = [];
    replay(counter, run.recording, { onTick: (sim) => seen.push(sim.tick) });
    expect(seen).toHaveLength(30);
  });

  it("verifies a replay that reaches the recorded hash, and says why one does not", () => {
    const run = runHeadless(counter, { seed: 5, ticks: 30, input: (t) => ({ add: t % 3 }) });
    expect(verify(counter, run.recording)).toMatchObject({ ok: true, ticks: 30 });
    const moved = { ...run.recording, inputs: [...run.recording.inputs.slice(1)] };
    expect(verify(counter, moved)).toMatchObject({
      ok: false,
      reason: expect.stringContaining("another state"),
    });
    const rescored = { ...run.recording, score: 1 };
    expect(verify(counter, rescored).reason).toContain("another score");
    const other = defineSim({ ...counter, dt: 0.2 });
    expect(verify(other, run.recording).reason).toContain("dt");
    const boom = defineSim<Counter, CounterInput>({
      ...counter,
      step: () => {
        throw new Error("boom");
      },
    });
    expect(verify(boom, run.recording).reason).toContain("boom");
  });

  it("rejects a definition with no usable step or an input that is not plain", () => {
    expect(() => defineSim({ ...counter, dt: 0 })).toThrow(/dt/);
    expect(() =>
      defineSim<number, Date>({ idle: new Date(0), init: () => 0, step: () => undefined }),
    ).toThrow(/idle/);
  });
});

describe("a recording as the run of the score API", () => {
  it("fits the run record: a seed text, [tick, text] inputs, duration_ms, the rest in meta", () => {
    const run = runHeadless(counter, {
      seed: 20261119,
      ticks: 12,
      input: (t) => ({ add: t > 4 ? 1 : 0 }),
      build: "1.4.0",
      meta: { level: "cave" },
    });
    const record = toRunRecord(run.recording);
    expect(record).toEqual({
      seed: "20261119",
      inputs: [[5, '{"add":1}']],
      duration_ms: 1200,
      build: "1.4.0",
      meta: expect.objectContaining({
        level: "cave",
        dt: 0.1,
        ticks: 12,
        hash: run.hash,
        score: run.score,
      }),
    });
    // What the server stores comes back through JSON unchanged.
    const stored = JSON.parse(JSON.stringify(record)) as typeof record;
    expect(fromRunRecord<CounterInput>(stored)).toEqual(run.recording);
    expect(verify(counter, fromRunRecord<CounterInput>(stored)).ok).toBe(true);
  });

  it("keeps a text seed and a config, and refuses a run another tool wrote", () => {
    const withConfig = defineSim<{ n: number }, number, string, { start: number }>({
      idle: 0,
      init: (_ctx, config) => ({ n: config.start }),
      step: (state, input) => {
        state.n += input;
      },
    });
    const run = runHeadless(withConfig, {
      seed: "2026-11-19",
      config: { start: 4 },
      ticks: 5,
      input: [1, 1],
    });
    const back = fromRunRecord<number, { start: number }>(toRunRecord(run.recording));
    expect(back.seed).toBe("2026-11-19");
    expect(back.config).toEqual({ start: 4 });
    expect(verify(withConfig, back).ok).toBe(true);
    expect(() => fromRunRecord({ seed: "1", inputs: [] })).toThrow(/not made by karni sim/);
  });
});

describe("the loop driver", () => {
  it("runs one tick per fixed step with the input of that step and passes the events on", () => {
    const recorder = createRecorder(counter, { seed: 1 });
    const events: string[][] = [];
    const reads = vi.fn(() => ({ add: 1 }));
    let playing = true;
    const loop = createSimLoop({
      target: recorder,
      input: reads,
      maxDt: 1,
      active: () => playing,
      onEvents: (e) => events.push([...e]),
    });
    expect(loop.fixed?.step).toBe(0.1);
    loop.tick(0.05);
    expect(recorder.sim.tick).toBe(0);
    loop.tick(0.05);
    expect(recorder.sim.tick).toBe(1);
    for (let n = 0; n < 4; n += 1) loop.tick(0.1);
    expect(recorder.sim.tick).toBe(5);
    expect(events).toEqual([["five"]]);
    playing = false;
    loop.tick(0.1);
    expect(recorder.sim.tick).toBe(5);
    expect(recorder.finish().inputs).toEqual([[0, { add: 1 }]]);
  });

  it("reads a target given as a function at every step, and reads active before beforeStep", () => {
    let recorder = createRecorder(counter, { seed: 1 });
    let screen: "menu" | "play" = "menu";
    const loop = createSimLoop({
      target: () => recorder,
      input: () => ({ add: 1 }),
      maxDt: 1,
      active: () => screen === "play",
      beforeStep: () => {
        if (screen === "menu") {
          screen = "play";
          recorder = createRecorder(counter, { seed: 2 });
        }
      },
    });
    loop.tick(0.1);
    // The step that left the menu did not run the sim.
    expect(recorder.sim.tick).toBe(0);
    loop.tick(0.1);
    expect(recorder.sim.tick).toBe(1);
    expect(recorder.sim.seed).toBe(2);
  });

  it("fails loudly when the target's step changes", () => {
    const errors: unknown[] = [];
    let dt = 0.1;
    const loop = createSimLoop({
      target: () => ({ dt, done: false, step: () => [] }),
      input: () => ({ add: 0 }),
      maxDt: 1,
      onError: (error) => errors.push(error),
    });
    dt = 0.2;
    loop.tick(0.1);
    expect(String(errors[0])).toContain("dt changed");
  });
});

describe("the test helpers", () => {
  it("runs headless for N ticks with scripted input and stops when the rules are done", () => {
    const run = runHeadless(counter, {
      seed: 1,
      ticks: 1000,
      input: [{ add: 30 }, { add: 30 }, { add: 50 }],
    });
    expect(run).toMatchObject({ done: true, ticks: 3 });
    expect(run.events).toEqual(["five", "five", "five"]);
    const longer = runHeadless(counter, {
      seed: 1,
      ticks: 8,
      stopWhenDone: false,
      input: [{ add: 100 }],
    });
    expect(longer.ticks).toBe(8);
  });

  it("passes determinism for pure rules", () => {
    expect(
      checkDeterminism(counter, { seed: 4, ticks: 50, input: (t) => ({ add: t % 2 }) }),
    ).toHaveLength(50);
  });

  it("fails determinism on a clock, on Math.random and on state kept outside the sim", () => {
    const leaky = (read: () => number) =>
      defineSim<{ v: number }, null>({
        idle: null,
        init: () => ({ v: 0 }),
        step: (state) => {
          state.v += read();
        },
      });
    const random = leaky(() => Math.random());
    expect(() => checkDeterminism(random, { seed: 1, ticks: 5 })).toThrow(SimTestError);
    expect(() => checkDeterminism(random, { seed: 1, ticks: 5 })).toThrow(/tick 1 /);
    let outside = 0;
    const kept = leaky(() => (outside += 1));
    expect(() => checkDeterminism(kept, { seed: 1, ticks: 5 })).toThrow(/not deterministic/);
  });

  it("fuzzes: random inputs for N ticks never throw and keep the declared invariants", () => {
    const report = fuzz(counter, { seed: 2, runs: 5, ticks: 40 });
    expect(report.runs).toBe(5);
    expect(report.scores).toHaveLength(5);
    expect(fuzz(counter, { seed: 2, runs: 5, ticks: 40 })).toEqual(report);
  });

  it("fuzz fails with the seed, the tick and a recording that replays the failure", () => {
    const fragile = defineSim<{ n: number }, { add: number }>({
      idle: { add: 0 },
      init: () => ({ n: 0 }),
      step: (state, input) => {
        state.n += input.add;
        if (state.n > 12) throw new Error("too high");
      },
      randomInput: (rng) => ({ add: rng.int(0, 3) }),
    });
    let failure: unknown;
    try {
      fuzz(fragile, { seed: 1, runs: 3, ticks: 100 });
    } catch (error) {
      failure = error;
    }
    expect(failure).toBeInstanceOf(FuzzFailure);
    const found = failure as FuzzFailure<{ add: number }>;
    expect(found.message).toContain("too high");
    expect(found.message).toContain(`seed ${found.seed}`);
    expect(() => replay(fragile, found.recording)).not.toThrow();
    // The recording stops at the failing tick, so one more step throws.
    const again = replay(fragile, found.recording);
    expect(() => again.step({ add: 3 })).toThrow("too high");
  });

  it("fuzz fails on NaN, on a broken invariant and on state that is not plain", () => {
    const make = (step: (s: { n: number; at?: Date }) => void, invariants = {}) =>
      defineSim<{ n: number; at?: Date }, null>({
        idle: null,
        init: () => ({ n: 1 }),
        step: (state) => step(state),
        randomInput: () => null,
        invariants,
      });
    expect(() =>
      fuzz(
        make((s) => void (s.n = s.n / 0 - s.n / 0)),
        { runs: 1, ticks: 3 },
      ),
    ).toThrow(/state.n is NaN/);
    expect(() =>
      fuzz(
        make((s) => void (s.n += 1), {
          "stays under three": (s: { n: number }) => s.n < 3 || "n reached three",
        }),
        { runs: 1, ticks: 10 },
      ),
    ).toThrow(/stays under three: n reached three/);
    expect(() =>
      fuzz(
        make((s) => void (s.at = new Date(0))),
        { runs: 1, ticks: 2 },
      ),
    ).toThrow(/Date/);
  });

  it("fuzz asks for random input when the rules have none", () => {
    const bare = defineSim<{ n: number }, null>({
      idle: null,
      init: () => ({ n: 0 }),
      step: () => undefined,
    });
    expect(() => fuzz(bare, { runs: 1, ticks: 1 })).toThrow(/randomInput/);
    expect(fuzz(bare, { runs: 2, ticks: 3, input: () => null }).ticks).toBe(6);
  });
});
