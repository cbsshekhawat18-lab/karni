import { describe, expect, it } from "vitest";
import { createRng, dateSeed, dayKey, deviceDailySeed, hashSeed } from "../src";

describe("createRng", () => {
  it("repeats the same sequence for the same seed, text or number", () => {
    const a = createRng("block-hopper");
    const b = createRng("block-hopper");
    const first = Array.from({ length: 5 }, () => a.next());
    expect(Array.from({ length: 5 }, () => b.next())).toEqual(first);
    expect(createRng(42).next()).toBe(createRng(42).next());
    expect(createRng(42).next()).not.toBe(createRng(43).next());
    // A known value, so a change to the generator breaks replays loudly.
    expect(createRng(1).next()).toBeCloseTo(0.6270739405881613, 12);
  });

  it("stays in range and covers it", () => {
    const rng = createRng(7);
    const seen = new Set<number>();
    for (let n = 0; n < 2000; n += 1) {
      const value = rng.int(1, 6);
      expect(value).toBeGreaterThanOrEqual(1);
      expect(value).toBeLessThanOrEqual(6);
      seen.add(value);
      const f = rng.float(-1, 1);
      expect(f).toBeGreaterThanOrEqual(-1);
      expect(f).toBeLessThan(1);
    }
    expect(seen.size).toBe(6);
  });

  it("picks, shuffles and decides chances deterministically", () => {
    const one = createRng(9);
    const two = createRng(9);
    expect(one.pick(["a", "b", "c"])).toBe(two.pick(["a", "b", "c"]));
    expect(one.shuffle([1, 2, 3, 4, 5])).toEqual(two.shuffle([1, 2, 3, 4, 5]));
    expect(one.shuffle([1, 2, 3, 4, 5]).sort()).toEqual([1, 2, 3, 4, 5]);
    expect(one.chance(0)).toBe(false);
    expect(one.chance(1)).toBe(true);
    expect(() => one.pick([])).toThrow(/empty/);
  });

  it("forks independent streams and resumes from a saved state", () => {
    const rng = createRng(5);
    const world = rng.fork("world");
    expect(world.next()).toBe(createRng(5).fork("world").next());
    expect(world.next()).not.toBe(rng.fork("loot").next());
    rng.next();
    const state = rng.state();
    const after = [rng.next(), rng.next()];
    expect([createRng(5).restore(state).next(), createRng(5).restore(state).next()]).toEqual([
      after[0],
      after[0],
    ]);
    const resumed = createRng(0).restore(state);
    expect([resumed.next(), resumed.next()]).toEqual(after);
  });
});

describe("date seeds", () => {
  it("hashes text to a stable 32-bit seed", () => {
    expect(hashSeed("")).toBe(0x811c9dc5);
    expect(hashSeed("a")).toBe(hashSeed("a"));
    expect(hashSeed("a")).not.toBe(hashSeed("b"));
  });

  it("names the day in a time zone", () => {
    const late = new Date(Date.UTC(2026, 10, 19, 23, 30));
    expect(dayKey(late)).toBe("2026-11-19");
    expect(dayKey(late, "Asia/Kolkata")).toBe("2026-11-20");
  });

  it("gives every device the same seed for a day and salt", () => {
    expect(dateSeed("2026-11-19", "block-hopper")).toBe(dateSeed("2026-11-19", "block-hopper"));
    expect(dateSeed("2026-11-19", "a")).not.toBe(dateSeed("2026-11-19", "b"));
    const daily = deviceDailySeed({ salt: "g", now: () => new Date(Date.UTC(2026, 0, 2, 12)) });
    expect(daily).toEqual({
      date: "2026-01-02",
      seed: dateSeed("2026-01-02", "g"),
      source: "device",
    });
  });
});
