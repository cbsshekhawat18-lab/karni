import { describe, expect, it } from "vitest";
import { createLoop } from "../src";

/** A loop driven by hand: no frame scheduler needed. */
function counted(step?: number) {
  const seen = { updates: 0, time: 0, renders: 0, afterFrames: 0, renderDt: [] as number[] };
  const loop = createLoop({
    step,
    update: (dt) => {
      seen.updates += 1;
      seen.time += dt;
    },
    render: (_alpha, dt) => {
      seen.renders += 1;
      seen.renderDt.push(dt);
    },
    afterFrame: () => {
      seen.afterFrames += 1;
    },
    requestFrame: () => 1,
    cancelFrame: () => undefined,
  });
  return { loop, seen };
}

describe("time scale", () => {
  it("runs fewer fixed steps of the same size in slow motion", () => {
    const { loop, seen } = counted(1 / 100);
    loop.timeScale = 0.5;
    for (let i = 0; i < 10; i += 1) loop.tick(0.02);
    // 0.2 s of real time at half speed is 0.1 s of game time: 10 steps of 0.01.
    expect(seen.updates).toBe(10);
    expect(seen.time).toBeCloseTo(0.1);
    // The render keeps the real frame time.
    expect(seen.renderDt.every((dt) => dt === 0.02)).toBe(true);
  });

  it("scales a variable step, freezes at 0 and refuses a bad value", () => {
    const { loop, seen } = counted();
    loop.timeScale = 2;
    loop.tick(0.01);
    expect(seen.time).toBeCloseTo(0.02);
    loop.timeScale = 0;
    loop.tick(0.01);
    expect(seen.time).toBeCloseTo(0.02);
    loop.timeScale = -3;
    expect(loop.timeScale).toBe(0);
    loop.timeScale = Number.NaN;
    expect(loop.timeScale).toBe(1);
    const slow = createLoop({ update: () => undefined, timeScale: 0.25 });
    expect(slow.timeScale).toBe(0.25);
  });
});

describe("hit-stop", () => {
  it("freezes updates for a while in real time, and goes on drawing", () => {
    const { loop, seen } = counted(1 / 100);
    loop.tick(0.01);
    expect(seen.updates).toBe(1);
    loop.hitStop(50);
    expect(loop.hitStopMs).toBe(50);
    for (let i = 0; i < 5; i += 1) loop.tick(0.01);
    expect(seen.updates).toBe(1);
    expect(seen.renders).toBe(6);
    expect(loop.hitStopMs).toBeCloseTo(0);
    loop.tick(0.01);
    expect(seen.updates).toBe(2);
  });

  it("keeps a press made during the stop for the first update after it", () => {
    const { loop, seen } = counted(1 / 100);
    loop.hitStop(30);
    loop.tick(0.01);
    loop.tick(0.01);
    // No step ran, so the input's edge flags were not cleared.
    expect(seen.afterFrames).toBe(0);
    loop.tick(0.01);
    loop.tick(0.01);
    expect(seen.updates).toBe(1);
    expect(seen.afterFrames).toBe(1);
  });

  it("keeps the longer of two stops, and does not count down while paused", () => {
    const { loop, seen } = counted();
    loop.hitStop(100);
    loop.hitStop(20);
    expect(loop.hitStopMs).toBe(100);
    loop.pause("menu");
    loop.tick(0.05);
    expect(loop.hitStopMs).toBe(100);
    loop.resume("menu");
    loop.tick(0.05);
    loop.tick(0.05);
    expect(seen.updates).toBe(0);
    expect(seen.afterFrames).toBe(1);
    loop.tick(0.05);
    expect(seen.updates).toBe(1);
    loop.hitStop(-5);
    loop.hitStop(Number.NaN);
    expect(loop.hitStopMs).toBe(0);
  });
});
