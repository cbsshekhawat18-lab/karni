import { describe, expect, it } from "vitest";
import { createLocalGame, weekStart, type LocalGameSetup } from "../src/client/local";
import { createStorage, memoryStorage } from "../src";

const setup: LocalGameSetup = {
  boards: { high: { title: "High score" }, time: { order: "asc", keep: 3 } },
  currencies: [{ key: "coins", title: "Coins", cap: 100 }],
  shop: [
    { key: "red-cap", title: "Red cap", slot: "hat", price: { currency: "coins", amount: 30 } },
    { key: "blue-cap", title: "Blue cap", slot: "hat", price: { currency: "coins", amount: 10 } },
  ],
  rewards: [
    { key: "daily-coins", title: "Daily", kind: "daily", currency: "coins", amount: 10 },
    { key: "ad-coins", title: "Ad", kind: "ad", currency: "coins", amount: 25, perDay: 2 },
  ],
  achievements: [{ key: "hopper", title: "Hopper", counter: "jumps", goal: 3 }],
};

const make = () => {
  let day = "2026-11-19";
  const storage = createStorage({ namespace: "g", backend: memoryStorage() });
  const local = createLocalGame(storage, setup, () => ({ day, now: new Date(`${day}T10:00:00Z`) }));
  return { local, setDay: (next: string) => (day = next) };
};

describe("createLocalGame", () => {
  it("keeps device boards per period, best first, by the board's order", () => {
    const { local, setDay } = make();
    expect(local.addScore("high", 10).improved).toEqual(["all", "daily", "weekly"]);
    expect(local.addScore("high", 5).improved).toEqual([]);
    setDay("2026-11-20");
    expect(local.addScore("high", 7).improved).toEqual(["daily"]);
    const all = local.board("high", "all", "You");
    expect(all.entries.map((e) => e.value)).toEqual([10, 7, 5]);
    expect(all.local).toBe(true);
    expect(local.board("high", "daily", "You").entries.map((e) => e.value)).toEqual([7]);
    for (const v of [30, 20, 40, 10]) local.addScore("time", v);
    expect(local.board("time", "all", "You").entries.map((e) => e.value)).toEqual([10, 20, 30]);
  });

  it("starts weeks on Monday", () => {
    expect(weekStart("2026-11-19")).toBe("2026-11-16");
    expect(weekStart("2026-11-16")).toBe("2026-11-16");
    expect(weekStart("2026-11-22")).toBe("2026-11-16");
  });

  it("grants, caps, buys and equips by the declared rules", () => {
    const { local } = make();
    expect(local.grant("coins", 150).balance).toBe(100);
    expect(local.buy("red-cap").balance.balance).toBe(70);
    expect(() => local.buy("red-cap")).toThrow(/GAME022/);
    local.buy("blue-cap");
    local.equip("red-cap", true);
    local.equip("blue-cap", true);
    const items = local.wallet().items;
    expect(items.find((i) => i.item === "red-cap")?.equipped).toBe(false);
    expect(items.find((i) => i.item === "blue-cap")?.equipped).toBe(true);
    expect(local.ledger().map((e) => e.reason)).toEqual(["purchase", "purchase", "reward"]);
    expect(() => local.grant("coins", -5)).toThrow(/GAME024/);
    expect(() => local.equip("green-cap", true)).toThrow(/GAME023/);
  });

  it("refuses a purchase without the money", () => {
    const { local } = make();
    expect(() => local.buy("red-cap")).toThrow(/GAME016/);
  });

  it("checks in once a day, keeps a streak with one day of grace", () => {
    const { local, setDay } = make();
    expect(local.checkIn()).toMatchObject({
      new_day: true,
      streak: { current: 1 },
      granted: [{ amount: 10 }],
    });
    expect(local.checkIn().new_day).toBe(false);
    setDay("2026-11-20");
    expect(local.checkIn().streak.current).toBe(2);
    setDay("2026-11-22"); // one day missed: grace
    expect(local.checkIn().streak.current).toBe(3);
    setDay("2026-11-25"); // two missed
    expect(local.checkIn().streak).toMatchObject({ current: 1, best: 3, checked_in: true });
  });

  it("limits ad rewards per day", () => {
    const { local, setDay } = make();
    local.claim("ad-coins");
    local.claim("ad-coins");
    expect(() => local.claim("ad-coins")).toThrow(/GAME017/);
    setDay("2026-11-20");
    expect(local.claim("ad-coins").granted.balance).toBe(75);
  });

  it("counts progress and unlocks achievements once", () => {
    const { local } = make();
    expect(local.progress([{ counter: "jumps", amount: 2 }]).unlocked).toEqual([]);
    expect(local.progress([{ counter: "jumps", amount: 1 }]).unlocked).toEqual([
      { key: "hopper", title: "Hopper" },
    ]);
    expect(local.progress([{ counter: "jumps", amount: 1 }]).unlocked).toEqual([]);
    expect(local.achievements()[0]).toMatchObject({ progress: 4, goal: 3 });
    expect(() => local.progress([{ counter: "jumps", amount: 0 }])).toThrow(/GAME024/);
  });
});
