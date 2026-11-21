import { describe, expect, it } from "vitest";
import { checkFrameBudget, frameMultiplier, frameStats } from "../src/smoke";

describe("the frame-time budget of the smoke run", () => {
  it("reads the median, the 95th percentile and the slowest of the frames after the warm-up", () => {
    const frames = [500, ...Array.from({ length: 99 }, (_, i) => 10 + i / 10), 90];
    const stats = frameStats(frames, 1);
    expect(stats.count).toBe(100);
    expect(stats.max).toBe(90);
    expect(stats.p50).toBeCloseTo(14.9, 1);
    expect(stats.p95).toBeCloseTo(19.4, 1);
    expect(frameStats([], 0)).toEqual({ count: 0, p50: 0, p95: 0, max: 0 });
    expect(frameStats([5, 6], 5).count).toBe(0);
  });

  it("passes a steady game and names the number that failed", () => {
    expect(checkFrameBudget({ count: 100, p50: 16, p95: 20, max: 60 })).toEqual([]);
    const slow = checkFrameBudget({ count: 100, p50: 30, p95: 55.5, max: 700 });
    expect(slow).toEqual([
      "frame time: the 95th percentile is 55.5 ms, over the budget of 40.0 ms",
      "frame time: the slowest frame took 700.0 ms, over the budget of 500.0 ms",
    ]);
  });

  it("takes the budget from the game and scales it for a slow runner", () => {
    const stats = { count: 100, p50: 30, p95: 55, max: 450 };
    expect(checkFrameBudget(stats, { p95: 60, max: 500 })).toEqual([]);
    expect(checkFrameBudget(stats, {}, 2)).toEqual([]);
    expect(checkFrameBudget(stats, { p95: 10 }, 5)).toEqual([
      "frame time: the 95th percentile is 55.0 ms, over the budget of 50.0 ms",
    ]);
  });

  it("reads the multiplier from the option, then the environment, else 1", () => {
    const before = process.env.KARNI_SMOKE_FRAME_MULTIPLIER;
    try {
      delete process.env.KARNI_SMOKE_FRAME_MULTIPLIER;
      expect(frameMultiplier()).toBe(1);
      process.env.KARNI_SMOKE_FRAME_MULTIPLIER = "2.5";
      expect(frameMultiplier()).toBe(2.5);
      expect(frameMultiplier(4)).toBe(4);
      process.env.KARNI_SMOKE_FRAME_MULTIPLIER = "nonsense";
      expect(frameMultiplier()).toBe(1);
    } finally {
      if (before === undefined) delete process.env.KARNI_SMOKE_FRAME_MULTIPLIER;
      else process.env.KARNI_SMOKE_FRAME_MULTIPLIER = before;
    }
  });
});
