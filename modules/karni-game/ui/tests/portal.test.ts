import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPortal, linkPortal, noPortal } from "../src";
import { fakePortal } from "../src/portal/adapters/fake";
import type { PortalAdapter } from "../src";

describe("createPortal", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("is a no-op without an SDK: ready at once, no ads, no reward", async () => {
    const portal = createPortal();
    expect(portal.name).toBe("none");
    await expect(portal.init()).resolves.toBe(true);
    portal.gameplayStart();
    portal.happyMoment();
    await expect(portal.interstitial()).resolves.toBe("unavailable");
    await expect(portal.rewarded()).resolves.toBe(false);
    expect(portal.canShowRewarded()).toBe(false);
    expect(portal.storage()).toBeNull();
    await expect(portal.hasAdblock()).resolves.toBe(false);
  });

  it("boots without the SDK when init passes the time limit, and uses it if it comes late", async () => {
    const adapter = fakePortal({ initMs: 10_000 });
    const portal = createPortal(adapter, { initTimeoutMs: 1000 });
    const errors: string[] = [];
    portal.on("error", ({ where }) => errors.push(where));
    const result = portal.init();
    await vi.advanceTimersByTimeAsync(1000);
    await expect(result).resolves.toBe(false);
    expect(errors).toEqual(["init"]);
    expect(portal.status).toBe("loading");
    await vi.advanceTimersByTimeAsync(9000);
    expect(portal.status).toBe("ready");
  });

  it("reports a refused init and keeps working as a no-op", async () => {
    const portal = createPortal(fakePortal({ failInit: true }));
    await expect(portal.init()).resolves.toBe(false);
    expect(portal.status).toBe("failed");
    await expect(portal.rewarded()).resolves.toBe(false);
    await expect(portal.interstitial()).resolves.toBe("unavailable");
  });

  it("replays calls made before the SDK is ready and pairs gameplay start and stop", async () => {
    const adapter = fakePortal({ initMs: 100 });
    const portal = createPortal(adapter);
    portal.loadingStart();
    portal.loadingFinished();
    portal.gameplayStart();
    portal.gameplayStart();
    const ready = portal.init();
    await vi.advanceTimersByTimeAsync(100);
    await ready;
    portal.gameplayStart();
    portal.gameplayStop();
    portal.gameplayStop();
    expect(adapter.calls).toEqual(["init", "loadingFinished", "gameplayStart", "gameplayStop"]);
  });

  it("stops gameplay for an ad, emits adstart and adend, and resumes after", async () => {
    const adapter = fakePortal({ adMs: 500 });
    const portal = createPortal(adapter);
    await portal.init();
    portal.gameplayStart();
    const seen: string[] = [];
    portal.on("adstart", (kind) => seen.push(`start:${kind}`));
    portal.on("adend", ({ kind, outcome }) => seen.push(`end:${kind}:${outcome}`));
    const ad = portal.interstitial("level-end");
    expect(portal.adPlaying).toBe("interstitial");
    portal.happyMoment(); // ignored during an ad
    await vi.advanceTimersByTimeAsync(500);
    await expect(ad).resolves.toBe("shown");
    expect(portal.adPlaying).toBeNull();
    expect(seen).toEqual(["start:interstitial", "end:interstitial:shown"]);
    expect(adapter.calls).toEqual([
      "init",
      "gameplayStart",
      "gameplayStop",
      "interstitial:level-end",
      "gameplayStart",
    ]);
  });

  it("keeps a cooldown between interstitials, from the last ad shown", async () => {
    let clock = 0;
    const portal = createPortal(fakePortal(), {
      interstitialCooldownMs: 60_000,
      now: () => clock,
    });
    await portal.init();
    await expect(portal.interstitial()).resolves.toBe("shown");
    clock = 30_000;
    expect(portal.canShowInterstitial()).toBe(false);
    await expect(portal.interstitial()).resolves.toBe("cooldown");
    clock = 60_000;
    await expect(portal.interstitial()).resolves.toBe("shown");
  });

  it("can hold the first interstitial back after start", async () => {
    let clock = 0;
    const portal = createPortal(fakePortal(), { firstInterstitialAfterMs: 5000, now: () => clock });
    await portal.init();
    await expect(portal.interstitial()).resolves.toBe("cooldown");
    clock = 5000;
    await expect(portal.interstitial()).resolves.toBe("shown");
  });

  it("does not start the cooldown when the SDK showed nothing", async () => {
    let clock = 0;
    const portal = createPortal(fakePortal({ interstitialShows: false }), { now: () => clock });
    await portal.init();
    await expect(portal.interstitial()).resolves.toBe("skipped");
    clock = 1;
    expect(portal.canShowInterstitial()).toBe(true);
  });

  it("rewards only on the SDK's completed event", async () => {
    for (const [end, expected] of [
      ["complete", true],
      ["dismiss", false],
      ["error", false],
      ["none", false],
    ] as const) {
      const portal = createPortal(fakePortal({ rewarded: end }));
      await portal.init();
      await expect(portal.rewarded()).resolves.toBe(expected);
    }
  });

  it("says a rewarded ad can be asked for only when ready, with an SDK that has them, and none playing", async () => {
    const portal = createPortal(fakePortal({ adMs: 500 }));
    expect(portal.canShowRewarded()).toBe(false);
    await portal.init();
    expect(portal.canShowRewarded()).toBe(true);
    const watching = portal.rewarded("continue");
    expect(portal.canShowRewarded()).toBe(false);
    await vi.advanceTimersByTimeAsync(500);
    await expect(watching).resolves.toBe(true);
    expect(portal.canShowRewarded()).toBe(true);
    const plain = createPortal(noPortal({ name: "web" }));
    await plain.init();
    expect(plain.canShowRewarded()).toBe(false);
  });

  it("treats anything but true from an adapter as no reward", async () => {
    const adapter: PortalAdapter = {
      name: "loose",
      init: () => Promise.resolve(),
      rewarded: () => Promise.resolve("yes" as unknown as boolean),
    };
    const portal = createPortal(adapter);
    await portal.init();
    await expect(portal.rewarded()).resolves.toBe(false);
  });

  it("a completed rewarded ad restarts the interstitial cooldown unless told not to", async () => {
    let clock = 100_000;
    const portal = createPortal(fakePortal(), { now: () => clock });
    await portal.init();
    await portal.rewarded();
    clock += 1000;
    expect(portal.canShowInterstitial()).toBe(false);
    const other = createPortal(fakePortal(), { now: () => clock, rewardedResetsCooldown: false });
    await other.init();
    await other.rewarded();
    expect(other.canShowInterstitial()).toBe(true);
  });

  it("gives up on an ad that never ends", async () => {
    const adapter: PortalAdapter = {
      name: "stuck",
      init: () => Promise.resolve(),
      rewarded: () => new Promise<boolean>(() => undefined),
      interstitial: () => new Promise<void>(() => undefined),
    };
    const portal = createPortal(adapter, { adTimeoutMs: 2000 });
    await portal.init();
    const reward = portal.rewarded();
    expect(portal.adPlaying).toBe("rewarded");
    await expect(portal.interstitial()).resolves.toBe("busy");
    await vi.advanceTimersByTimeAsync(2000);
    await expect(reward).resolves.toBe(false);
    expect(portal.adPlaying).toBeNull();
    const ad = portal.interstitial();
    await vi.advanceTimersByTimeAsync(2000);
    await expect(ad).resolves.toBe("error");
  });

  it("never lets a throwing SDK call reach the game", async () => {
    const adapter: PortalAdapter = {
      name: "broken",
      init: () => Promise.resolve(),
      gameplayStart: () => {
        throw new Error("boom");
      },
      happyMoment: () => {
        throw new Error("boom");
      },
      storage: () => {
        throw new Error("boom");
      },
    };
    const portal = createPortal(adapter);
    const errors: string[] = [];
    portal.on("error", ({ where }) => errors.push(where));
    await portal.init();
    expect(() => portal.gameplayStart()).not.toThrow();
    expect(() => portal.happyMoment()).not.toThrow();
    expect(portal.storage()).toBeNull();
    expect(errors).toEqual(["gameplayStart", "happyMoment", "storage"]);
  });

  it("forwards the portal's mute setting and pause requests", async () => {
    const adapter = fakePortal({ muted: true });
    const portal = createPortal(adapter);
    const mutes: boolean[] = [];
    const pauses: boolean[] = [];
    portal.on("mute", (value) => mutes.push(value));
    portal.on("pause", (value) => pauses.push(value));
    await portal.init();
    expect(portal.muted).toBe(true);
    adapter.setMuted(false);
    adapter.requestPause(true);
    adapter.requestPause(false);
    expect(mutes).toEqual([true, false]);
    expect(pauses).toEqual([true, false]);
  });

  it("offers the portal's data module once ready", async () => {
    const store = new Map<string, string>();
    const storage = {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => void store.set(key, value),
      removeItem: (key: string) => void store.delete(key),
    };
    const portal = createPortal(fakePortal({ storage }));
    expect(portal.storage()).toBeNull();
    await portal.init();
    expect(portal.storage()).toBe(storage);
  });

  it("init is called once however often it is asked", async () => {
    const adapter = fakePortal();
    const portal = createPortal(adapter);
    await Promise.all([portal.init(), portal.init()]);
    await portal.init();
    expect(adapter.calls.filter((call) => call === "init")).toHaveLength(1);
  });

  it("noPortal takes a name for the builds that have no SDK", () => {
    expect(noPortal({ name: "itch" }).name).toBe("itch");
  });
});

describe("linkPortal", () => {
  it("mutes the ad and portal sources apart, pauses the loop and lets go of keys", async () => {
    vi.useFakeTimers();
    const adapter = fakePortal({ adMs: 100, muted: true });
    const portal = createPortal(adapter);
    await portal.init();
    const log: string[] = [];
    const unlink = linkPortal(portal, {
      audio: {
        setMuted: (source, muted) => log.push(`mute:${source}:${muted}`),
        pause: (reason) => log.push(`audio-pause:${reason}`),
        resume: (reason) => log.push(`audio-resume:${reason}`),
      },
      loop: {
        pause: (reason) => log.push(`pause:${reason}`),
        resume: (reason) => log.push(`resume:${reason}`),
      },
      input: { releaseAll: () => log.push("release") },
    });
    const ad = portal.rewarded();
    await vi.advanceTimersByTimeAsync(100);
    await ad;
    adapter.setMuted(false);
    adapter.requestPause(true);
    unlink();
    adapter.requestPause(false);
    expect(log).toEqual([
      "mute:portal:true",
      "mute:ad:true",
      "audio-pause:ad",
      "pause:ad",
      "release",
      "mute:ad:false",
      "audio-resume:ad",
      "resume:ad",
      "mute:portal:false",
      "pause:portal",
      "audio-pause:portal",
    ]);
    vi.useRealTimers();
  });
});
