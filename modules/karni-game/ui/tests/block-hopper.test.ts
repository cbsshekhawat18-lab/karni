import { describe, expect, it } from "vitest";
import {
  WORLD,
  createHopper,
  revive,
  score,
  stepHopper,
  type Hopper,
  type HopperInput,
} from "../example/block-hopper/src/core";

const idle: HopperInput = { left: false, right: false, jump: false };

/** Play a run headless: a seed and a list of (step, input) changes. */
function play(
  seed: number,
  plan: (step: number, hopper: Hopper) => HopperInput,
  steps: number,
): Hopper {
  const hopper = createHopper(seed);
  for (let n = 0; n < steps && hopper.alive; n += 1) stepHopper(hopper, plan(n, hopper));
  return hopper;
}

describe("Block Hopper's rules", () => {
  it("stands on the first platform, runs and jumps", () => {
    const hopper = createHopper(7);
    for (let n = 0; n < 60; n += 1) stepHopper(hopper, idle);
    expect(hopper.grounded).toBe(true);
    expect(stepHopper(hopper, { ...idle, jump: true })).toContain("jump");
    expect(hopper.vy).toBeLessThan(0);
    for (let n = 0; n < 240; n += 1) stepHopper(hopper, { ...idle, right: true });
    expect(hopper.x).toBeGreaterThan(200);
  });

  it("falls when it walks off the start, and the run is over", () => {
    const hopper = play(3, () => ({ ...idle, left: true }), 2000);
    expect(hopper.alive).toBe(false);
    expect(score(hopper)).toBe(0);
  });

  it("lays every platform within jumping reach", () => {
    const hopper = createHopper(11);
    for (let n = 0; n < 50; n += 1) {
      hopper.x += WORLD.width;
      stepHopper(hopper, idle);
    }
    for (let i = 1; i < hopper.platforms.length; i += 1) {
      const a = hopper.platforms[i - 1];
      const b = hopper.platforms[i];
      if (!a || !b) continue;
      expect(b.x - (a.x + a.w)).toBeLessThanOrEqual(110);
      expect(a.y - b.y).toBeLessThanOrEqual(50);
    }
  });

  it("replays a run exactly from its seed and input log", () => {
    const plan = (step: number, hopper: Hopper): HopperInput => ({
      left: false,
      right: true,
      jump: hopper.grounded && step % 50 === 0,
    });
    const a = play(42, plan, 3000);
    const b = play(42, plan, 3000);
    expect(score(a)).toBe(score(b));
    expect(a.x).toBe(b.x);
    expect(score(a)).toBeGreaterThan(0);
    expect(play(43, plan, 3000).platforms[3]).not.toEqual(a.platforms[3]);
  });

  it("revives a fallen player on a platform behind it", () => {
    const hopper = play(5, () => ({ ...idle, left: true }), 2000);
    revive(hopper);
    expect(hopper.alive).toBe(true);
    for (let n = 0; n < 30; n += 1) stepHopper(hopper, idle);
    expect(hopper.grounded).toBe(true);
  });
});
