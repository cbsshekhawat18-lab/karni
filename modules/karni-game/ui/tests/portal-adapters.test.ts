import { afterEach, describe, expect, it, vi } from "vitest";
import { createPortal } from "../src";
import { crazyGames, type CrazyGamesSdk } from "../src/portal/adapters/crazygames";
import { gameDistribution } from "../src/portal/adapters/gamedistribution";
import { poki, type PokiSdk } from "../src/portal/adapters/poki";
import { y8, type Y8Sdk } from "../src/portal/adapters/y8";

type Win = Record<string, unknown>;
const win = globalThis as unknown as Win;

afterEach(() => {
  for (const key of ["PokiSDK", "CrazyGames", "gdsdk", "GD_OPTIONS", "y8"]) {
    Reflect.deleteProperty(win, key);
  }
  document.head.innerHTML = "";
});

describe("poki", () => {
  const sdk = (reward: boolean): PokiSdk & { log: string[] } => {
    const log: string[] = [];
    return {
      log,
      init: async () => void log.push("init"),
      gameLoadingFinished: () => void log.push("loaded"),
      gameplayStart: () => void log.push("start"),
      gameplayStop: () => void log.push("stop"),
      commercialBreak: async (onStart) => {
        onStart?.();
        log.push("break");
      },
      rewardedBreak: async (onStart) => {
        onStart?.();
        log.push("rewarded");
        return reward;
      },
    };
  };

  it("finds window.PokiSDK and maps every call", async () => {
    const fake = sdk(true);
    win.PokiSDK = fake;
    const portal = createPortal(poki());
    await expect(portal.init()).resolves.toBe(true);
    portal.loadingFinished();
    portal.gameplayStart();
    await expect(portal.interstitial()).resolves.toBe("shown");
    await expect(portal.rewarded()).resolves.toBe(true);
    expect(fake.log).toEqual([
      "init",
      "loaded",
      "start",
      "stop",
      "break",
      "start",
      "stop",
      "rewarded",
      "start",
    ]);
  });

  it("gives no reward when rewardedBreak resolves false", async () => {
    const portal = createPortal(poki({ sdk: () => sdk(false) }));
    await portal.init();
    await expect(portal.rewarded()).resolves.toBe(false);
  });

  it("fails init when the SDK never appears (blocked script)", async () => {
    const portal = createPortal(poki({ waitMs: 20 }));
    await expect(portal.init()).resolves.toBe(false);
    expect(portal.status).toBe("failed");
  });
});

describe("crazyGames", () => {
  const sdk = (
    end: "finished" | "error",
    environment = "crazygames",
  ): CrazyGamesSdk & { log: string[]; change(muted: boolean): void } => {
    const log: string[] = [];
    const listeners: ((settings: { muteAudio?: boolean }) => void)[] = [];
    return {
      log,
      environment,
      init: async () => void log.push("init"),
      game: {
        gameplayStart: () => void log.push("start"),
        gameplayStop: () => void log.push("stop"),
        happytime: () => void log.push("happy"),
        loadingStart: () => void log.push("loadingStart"),
        loadingStop: () => void log.push("loadingStop"),
        settings: { muteAudio: true },
        addSettingsChangeListener: (listener) => void listeners.push(listener),
        removeSettingsChangeListener: () => undefined,
      },
      ad: {
        requestAd: (type, callbacks) => {
          log.push(`ad:${type}`);
          callbacks.adStarted?.();
          if (end === "finished") callbacks.adFinished?.();
          else callbacks.adError?.({ code: "unfilled" });
        },
        hasAdblock: async () => true,
      },
      data: {
        getItem: () => "saved",
        setItem: () => undefined,
        removeItem: () => undefined,
      },
      change(muted) {
        for (const listener of listeners) listener({ muteAudio: muted });
      },
    };
  };

  it("maps calls, reads the site's mute setting and offers the data module", async () => {
    const fake = sdk("finished");
    win.CrazyGames = { SDK: fake };
    const portal = createPortal(crazyGames());
    const mutes: boolean[] = [];
    portal.on("mute", (muted) => mutes.push(muted));
    await portal.init();
    portal.loadingStart();
    portal.loadingFinished();
    portal.happyMoment();
    await expect(portal.interstitial()).resolves.toBe("shown");
    await expect(portal.rewarded()).resolves.toBe(true);
    fake.change(false);
    expect(mutes).toEqual([true, false]);
    expect(portal.storage()?.getItem("x")).toBe("saved");
    await expect(portal.hasAdblock()).resolves.toBe(true);
    expect(fake.log).toEqual([
      "init",
      "loadingStart",
      "loadingStop",
      "happy",
      "ad:midgame",
      "ad:rewarded",
    ]);
  });

  it("gives no reward on adError", async () => {
    const portal = createPortal(crazyGames({ sdk: () => sdk("error") }));
    await portal.init();
    await expect(portal.rewarded()).resolves.toBe(false);
  });

  it("treats the disabled environment (another domain) as no SDK", async () => {
    const portal = createPortal(crazyGames({ sdk: () => sdk("finished", "disabled") }));
    await expect(portal.init()).resolves.toBe(false);
    expect(portal.status).toBe("failed");
  });
});

describe("gameDistribution", () => {
  type OnEvent = (event: { name: string }) => void;
  const options = (): { onEvent: OnEvent } => {
    const gd = win.GD_OPTIONS as { gameId: string; onEvent: OnEvent } | undefined;
    if (!gd) throw new Error("GD_OPTIONS not set");
    return gd;
  };

  it("sets GD_OPTIONS from config, loads the script and waits for SDK_READY", async () => {
    const portal = createPortal(gameDistribution({ gameId: "test-game-id" }));
    const ready = portal.init();
    const script = document.getElementById("gamedistribution-jssdk") as HTMLScriptElement;
    expect(script.src).toBe("https://html5.api.gamedistribution.com/main.min.js");
    expect((win.GD_OPTIONS as { gameId: string }).gameId).toBe("test-game-id");
    options().onEvent({ name: "SDK_READY" });
    await expect(ready).resolves.toBe(true);
  });

  it("refuses to start without a gameId", async () => {
    const portal = createPortal(gameDistribution({ gameId: "" }));
    await expect(portal.init()).resolves.toBe(false);
  });

  it("rewards only after SDK_REWARDED_WATCH_COMPLETE, and forwards pauses outside ads", async () => {
    let watch = true;
    win.gdsdk = {
      showAd: async (type?: string) => {
        options().onEvent({ name: "SDK_GAME_PAUSE" });
        if (type === "rewarded" && watch)
          options().onEvent({ name: "SDK_REWARDED_WATCH_COMPLETE" });
        options().onEvent({ name: "SDK_GAME_START" });
      },
    };
    const portal = createPortal(gameDistribution({ gameId: "g", rewardGraceMs: 1 }));
    const pauses: boolean[] = [];
    portal.on("pause", (paused) => pauses.push(paused));
    const ready = portal.init();
    options().onEvent({ name: "SDK_READY" });
    await ready;
    await expect(portal.interstitial()).resolves.toBe("shown");
    await expect(portal.rewarded()).resolves.toBe(true);
    watch = false;
    await expect(portal.rewarded()).resolves.toBe(false);
    expect(pauses).toEqual([]);
    options().onEvent({ name: "SDK_GAME_PAUSE" });
    options().onEvent({ name: "SDK_GAME_START" });
    expect(pauses).toEqual([true, false]);
  });

  it("gives no reward when showAd rejects", async () => {
    win.gdsdk = { showAd: () => Promise.reject(new Error("no fill")) };
    const portal = createPortal(gameDistribution({ gameId: "g" }));
    const ready = portal.init();
    options().onEvent({ name: "SDK_READY" });
    await ready;
    await expect(portal.rewarded()).resolves.toBe(false);
  });
});

describe("y8", () => {
  const sdk = (status: "viewed" | "dismissed"): Y8Sdk & { log: string[] } => {
    const log: string[] = [];
    return {
      log,
      init: (app, ads) => {
        log.push(`init:${app.appId}:${ads?.gameId ?? "no-ads"}`);
        ads?.onReady?.();
      },
      showAd: (adBreak) => {
        log.push(`${adBreak.type}:${adBreak.name}`);
        adBreak.beforeReward?.(() => log.push("show"));
        adBreak.beforeAd?.();
        if (status === "viewed") adBreak.adViewed?.();
        else adBreak.adDismissed?.();
        adBreak.adBreakDone?.({ breakStatus: status });
      },
    };
  };

  it("waits for y8sdk.ready, starts with ids from config, maps breaks", async () => {
    const fake = sdk("viewed");
    win.y8 = {
      sdk: () => fake,
      emitReadyEvent: () => window.dispatchEvent(new Event("y8sdk.ready")),
    };
    const portal = createPortal(y8({ appId: "app-1", gameId: "game-1" }));
    await expect(portal.init()).resolves.toBe(true);
    await expect(portal.interstitial("level-end")).resolves.toBe("shown");
    await expect(portal.rewarded("extra-life")).resolves.toBe(true);
    expect(fake.log).toEqual(["init:app-1:game-1", "next:level-end", "reward:extra-life", "show"]);
  });

  it("gives no reward for a dismissed ad", async () => {
    const portal = createPortal(y8({ appId: "a", gameId: "g", sdk: () => sdk("dismissed") }));
    await portal.init();
    await expect(portal.rewarded()).resolves.toBe(false);
  });

  it("has no ads without a gameId", async () => {
    const fake = sdk("viewed");
    const portal = createPortal(y8({ appId: "a", sdk: () => fake }));
    await portal.init();
    await expect(portal.rewarded()).resolves.toBe(false);
    expect(fake.log).toEqual(["init:a:no-ads"]);
  });

  it("refuses to start without an appId", async () => {
    vi.useFakeTimers();
    const portal = createPortal(y8({ appId: "" }));
    const ready = portal.init();
    await vi.runAllTimersAsync();
    await expect(ready).resolves.toBe(false);
    vi.useRealTimers();
  });
});
