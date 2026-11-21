import { describe, expect, it } from "vitest";
import {
  checkDeterminism,
  createSim,
  fuzz,
  replay,
  runHeadless,
  verify,
  type InputScript,
} from "../src/sim";
import { checkRules } from "../src/tooling";
import {
  WORLD,
  hopperSim,
  score,
  type Hopper,
  type HopperEvent,
  type HopperInput,
} from "../example/block-hopper/src/rules";

const idle: HopperInput = hopperSim.idle;
type Script = InputScript<Hopper, HopperInput, HopperEvent, undefined>;

const runRight: Script = (tick, sim) => ({
  ...idle,
  right: true,
  jump: sim.state.grounded && tick % 50 === 0,
});
/** A bot that runs right and jumps at the edge of the platform it stands on. */
const bot: Script = (_tick, sim) => {
  const h = sim.state;
  const under = h.platforms.find((p) => h.x + WORLD.size > p.x && h.x < p.x + p.w);
  const atEdge = under ? h.x + WORLD.size >= under.x + under.w - 6 : false;
  return { ...idle, right: true, jump: h.grounded && atEdge };
};
const walkLeft: Script = () => ({ ...idle, left: true });

describe("Block Hopper's rules on the simulation contract", () => {
  it("stands on the first platform, runs and jumps", () => {
    const sim = createSim(hopperSim, { seed: 7 });
    for (let n = 0; n < 60; n += 1) sim.step(idle);
    expect(sim.state.grounded).toBe(true);
    expect(sim.step({ ...idle, jump: true })).toContain("jump");
    expect(sim.state.vy).toBeLessThan(0);
    for (let n = 0; n < 240; n += 1) sim.step({ ...idle, right: true });
    expect(sim.state.x).toBeGreaterThan(200);
  });

  it("falls when it walks off the start, and the run is over", () => {
    const run = runHeadless(hopperSim, { seed: 3, ticks: 2000, input: walkLeft });
    expect(run.done).toBe(true);
    expect(run.events).toContain("fall");
    expect(run.score).toBe(0);
  });

  it("lays every platform within jumping reach", () => {
    const sim = createSim(hopperSim, { seed: 11 });
    for (let n = 0; n < 50; n += 1) {
      sim.state.x += WORLD.width;
      sim.step(idle);
    }
    const { platforms } = sim.state;
    for (let i = 1; i < platforms.length; i += 1) {
      const a = platforms[i - 1];
      const b = platforms[i];
      if (!a || !b) continue;
      expect(b.x - (a.x + a.w)).toBeLessThanOrEqual(110);
      expect(a.y - b.y).toBeLessThanOrEqual(50);
    }
  });

  it("keeps the score of a known seed and its input script", () => {
    const run = runHeadless(hopperSim, { seed: 42, ticks: 6000, input: bot });
    expect(run.score).toBeGreaterThan(100);
    expect(run.score).toBe(score(run.sim.state));
    // A golden run: a change to the rules or to the hash changes these two.
    expect({ ticks: run.ticks, score: run.score, hash: run.hash }).toMatchInlineSnapshot(`
      {
        "hash": "d6fffd6b9b799124",
        "score": 231,
        "ticks": 1331,
      }
    `);
  });

  it("gives another world for another seed", () => {
    const a = runHeadless(hopperSim, { seed: 42, ticks: 600, input: runRight });
    const b = runHeadless(hopperSim, { seed: 43, ticks: 600, input: runRight });
    expect(b.sim.state.platforms[3]).not.toEqual(a.sim.state.platforms[3]);
    expect(b.hash).not.toBe(a.hash);
  });

  it("is deterministic: the same seed and inputs give the same hash every tick", () => {
    const hashes = checkDeterminism(hopperSim, { seed: 9, ticks: 800, input: runRight, every: 20 });
    expect(hashes).toHaveLength(40);
  });

  it("survives random inputs for many ticks and keeps its invariants", () => {
    const report = fuzz(hopperSim, { seed: 5, runs: 12, ticks: 1500, pastDone: true });
    expect(report.runs).toBe(12);
    expect(report.ticks).toBe(12 * 1500);
  });

  it("revives a fallen player on a platform behind it, as an input", () => {
    const fall = runHeadless(hopperSim, { seed: 5, ticks: 2000, input: walkLeft });
    expect(fall.done).toBe(true);
    const sim = fall.sim;
    sim.step({ ...idle, revive: true });
    expect(sim.state.alive).toBe(true);
    for (let n = 0; n < 30; n += 1) sim.step(idle);
    expect(sim.state.grounded).toBe(true);
  });

  it("verifies a run that used the rewarded continue, and refuses an edited one", () => {
    const script: Script = (tick, sim) =>
      !sim.state.alive
        ? { ...idle, revive: true }
        : tick < 2000
          ? { ...idle, left: true }
          : runRight(tick, sim);
    const run = runHeadless(hopperSim, {
      seed: 5,
      ticks: 3000,
      input: script,
      stopWhenDone: false,
    });
    expect(verify(hopperSim, run.recording).ok).toBe(true);
    const edited = { ...run.recording, score: run.recording.score + 100 };
    expect(verify(hopperSim, edited).ok).toBe(false);
    expect(replay(hopperSim, run.recording).hash()).toBe(run.hash);
  });

  it("has a rules folder with no clock, Math.random, page or network", () => {
    expect(checkRules("example/block-hopper/src/rules")).toEqual([]);
  });
});
