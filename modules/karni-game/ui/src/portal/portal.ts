import { createEmitter } from "../internal/emitter";
import { withTimeout } from "../internal/time";
import { noPortal } from "./adapters/none";
import type {
  AdKind,
  InterstitialOutcome,
  Portal,
  PortalAdapter,
  PortalEvents,
  PortalOptions,
  PortalStatus,
} from "./types";

const DEFAULTS = {
  initTimeoutMs: 5000,
  adTimeoutMs: 90_000,
  interstitialCooldownMs: 60_000,
  firstInterstitialAfterMs: 0,
  rewardedResetsCooldown: true,
};

/**
 * Wrap a portal adapter in the rules every game needs: a time limit on the
 * SDK's start, gameplay start and stop sent in pairs, an interstitial
 * cooldown, a reward only on the SDK's completed event, and mute and pause
 * events around every ad. With no adapter (or `noPortal()`) every call is a
 * no-op, so the same game runs on a plain web page.
 */
export function createPortal(
  adapter: PortalAdapter = noPortal(),
  options: PortalOptions = {},
): Portal {
  const settings = { ...DEFAULTS, ...options };
  const now = options.now ?? Date.now;
  const events = createEmitter<PortalEvents>();
  const created = now();

  let status: PortalStatus = "idle";
  let initPromise: Promise<boolean> | null = null;
  let adPlaying: AdKind | null = null;
  let muted = false;
  let wantGameplay = false;
  let sdkGameplay = false;
  let loading: "none" | "started" | "finished" = "none";
  let loadingSent: "none" | "started" | "finished" = "none";
  let lastAdEnd = Number.NEGATIVE_INFINITY;

  const report = (where: string, error: unknown): void => {
    events.emit("error", { where, error });
  };
  const call = (where: string, fn: (() => void) | undefined): void => {
    if (!fn) return;
    try {
      fn.call(adapter);
    } catch (error) {
      report(where, error);
    }
  };

  /** Bring the SDK in line with what the game asked for, once it is ready and no ad plays. */
  const sync = (): void => {
    if (status !== "ready" || adPlaying) return;
    if (loading === "started" && loadingSent === "none") {
      call("loadingStart", adapter.loadingStart);
      loadingSent = "started";
    }
    if (loading === "finished" && loadingSent !== "finished") {
      call("loadingFinished", adapter.loadingFinished);
      loadingSent = "finished";
    }
    if (wantGameplay && !sdkGameplay) {
      call("gameplayStart", adapter.gameplayStart);
      sdkGameplay = true;
    } else if (!wantGameplay && sdkGameplay) {
      call("gameplayStop", adapter.gameplayStop);
      sdkGameplay = false;
    }
  };

  const becomeReady = (): void => {
    if (status === "ready") return;
    status = "ready";
    try {
      adapter.onMute?.((value) => {
        if (value === muted) return;
        muted = value;
        events.emit("mute", value);
      });
      adapter.onPause?.((value) => events.emit("pause", value));
    } catch (error) {
      report("subscribe", error);
    }
    events.emit("ready", undefined);
    sync();
  };

  const runAd = async <T>(
    kind: AdKind,
    show: (onStart: () => void) => Promise<T>,
    fallback: T,
  ): Promise<{ value: T; started: boolean; failed: boolean }> => {
    adPlaying = kind;
    if (sdkGameplay) {
      call("gameplayStop", adapter.gameplayStop);
      sdkGameplay = false;
    }
    events.emit("adstart", kind);
    let started = false;
    try {
      const value = await withTimeout(
        show(() => {
          started = true;
        }),
        settings.adTimeoutMs,
        `${adapter.name} ${kind} ad`,
      );
      return { value, started, failed: false };
    } catch (error) {
      report(kind, error);
      return { value: fallback, started, failed: true };
    } finally {
      adPlaying = null;
    }
  };

  const portal: Portal = {
    name: adapter.name,
    get status() {
      return status;
    },
    get adPlaying() {
      return adPlaying;
    },
    get muted() {
      return muted;
    },

    init() {
      if (initPromise) return initPromise;
      status = "loading";
      let started: Promise<void>;
      try {
        started = Promise.resolve(adapter.init());
      } catch (error) {
        started = Promise.reject(error);
      }
      // A slow SDK may still come up after the time limit: it is used from then on.
      started.then(becomeReady, (error: unknown) => {
        status = "failed";
        report("init", error);
      });
      initPromise = withTimeout(started, settings.initTimeoutMs, `${adapter.name} init`).then(
        () => true,
        (error: unknown) => {
          if (status === "loading") report("init", error);
          return false;
        },
      );
      return initPromise;
    },

    loadingStart() {
      if (loading === "none") loading = "started";
      sync();
    },
    loadingFinished() {
      loading = "finished";
      sync();
    },
    gameplayStart() {
      wantGameplay = true;
      sync();
    },
    gameplayStop() {
      wantGameplay = false;
      sync();
    },
    happyMoment() {
      if (status === "ready" && !adPlaying) call("happyMoment", adapter.happyMoment);
    },

    canShowInterstitial() {
      if (status !== "ready" || adPlaying || !adapter.interstitial) return false;
      const at = now();
      return (
        at - created >= settings.firstInterstitialAfterMs &&
        at - lastAdEnd >= settings.interstitialCooldownMs
      );
    },

    async interstitial(placement = "interstitial") {
      if (adPlaying) return "busy";
      const show = adapter.interstitial;
      if (status !== "ready" || !show) return "unavailable";
      if (!portal.canShowInterstitial()) return "cooldown";
      const result = await runAd(
        "interstitial",
        (onStart) => show.call(adapter, onStart, placement),
        undefined,
      );
      const outcome: InterstitialOutcome = result.failed
        ? "error"
        : result.started
          ? "shown"
          : "skipped";
      if (result.started) lastAdEnd = now();
      events.emit("adend", { kind: "interstitial", outcome });
      sync();
      return outcome;
    },

    canShowRewarded() {
      return status === "ready" && !adPlaying && Boolean(adapter.rewarded);
    },

    async rewarded(placement = "rewarded") {
      const show = adapter.rewarded;
      if (adPlaying || status !== "ready" || !show) return false;
      const result = await runAd(
        "rewarded",
        (onStart) => show.call(adapter, onStart, placement),
        false,
      );
      // Only the SDK's own completed signal counts: anything but `true` is no reward.
      const rewarded = result.value === true && !result.failed;
      if (rewarded && settings.rewardedResetsCooldown) lastAdEnd = now();
      events.emit("adend", { kind: "rewarded", outcome: rewarded ? "rewarded" : "not-rewarded" });
      sync();
      return rewarded;
    },

    storage() {
      if (status !== "ready" || !adapter.storage) return null;
      try {
        return adapter.storage();
      } catch (error) {
        report("storage", error);
        return null;
      }
    },

    async hasAdblock() {
      if (!adapter.hasAdblock) return false;
      try {
        return (await adapter.hasAdblock()) === true;
      } catch (error) {
        report("hasAdblock", error);
        return false;
      }
    },

    on: events.on,
  };
  return portal;
}
