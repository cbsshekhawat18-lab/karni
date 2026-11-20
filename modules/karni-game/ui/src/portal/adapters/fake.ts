import type { StorageLike } from "../../save/types";
import type { PortalAdapter } from "../types";

export interface FakePortalOptions {
  name?: string;
  /** How a rewarded ad ends. Default "complete". */
  rewarded?: "complete" | "dismiss" | "error" | "none";
  /** Whether an interstitial shows (calls its start callback). Default true. */
  interstitialShows?: boolean;
  /** How long an ad plays, in ms. Default 0. */
  adMs?: number;
  /** How long `init` takes, in ms. Default 0. Use a long time to test the init time limit. */
  initMs?: number;
  /** `init` rejects, as with an ad blocker. */
  failInit?: boolean;
  /** The portal's mute setting at start. */
  muted?: boolean;
  /** A data module. */
  storage?: StorageLike;
}

/** A fake portal adapter with a log of every call and hooks to drive its events. */
export interface FakePortalAdapter extends PortalAdapter {
  readonly calls: string[];
  /** Change the portal's mute setting, as a player toggling it on the portal page. */
  setMuted(muted: boolean): void;
  /** Ask the game to pause or resume, as a portal does around its own overlays. */
  requestPause(paused: boolean): void;
}

const wait = (ms: number): Promise<void> =>
  ms > 0 ? new Promise((resolve) => setTimeout(resolve, ms)) : Promise.resolve();

/**
 * A portal for development and tests: ads that play for `adMs` and end the
 * way the options say, without any SDK or network. Never ship it: the
 * registry rows name real adapters, and a development build picks it only
 * when asked.
 */
export function fakePortal(options: FakePortalOptions = {}): FakePortalAdapter {
  const calls: string[] = [];
  const muteListeners = new Set<(muted: boolean) => void>();
  const pauseListeners = new Set<(paused: boolean) => void>();
  let muted = options.muted ?? false;
  return {
    name: options.name ?? "fake",
    calls,
    async init() {
      calls.push("init");
      await wait(options.initMs ?? 0);
      if (options.failInit) throw new Error("fake portal: init refused");
    },
    loadingStart: () => void calls.push("loadingStart"),
    loadingFinished: () => void calls.push("loadingFinished"),
    gameplayStart: () => void calls.push("gameplayStart"),
    gameplayStop: () => void calls.push("gameplayStop"),
    happyMoment: () => void calls.push("happyMoment"),
    async interstitial(onStart, placement) {
      calls.push(`interstitial:${placement}`);
      if (options.interstitialShows ?? true) onStart();
      await wait(options.adMs ?? 0);
    },
    async rewarded(onStart, placement) {
      calls.push(`rewarded:${placement}`);
      const end = options.rewarded ?? "complete";
      if (end === "none") return false;
      onStart();
      await wait(options.adMs ?? 0);
      if (end === "error") throw new Error("fake portal: ad failed");
      return end === "complete";
    },
    onMute(listener) {
      muteListeners.add(listener);
      listener(muted);
      return () => muteListeners.delete(listener);
    },
    onPause(listener) {
      pauseListeners.add(listener);
      return () => pauseListeners.delete(listener);
    },
    storage: () => options.storage ?? null,
    hasAdblock: () => Promise.resolve(options.failInit ?? false),
    setMuted(value) {
      muted = value;
      for (const listener of muteListeners) listener(value);
    },
    requestPause(paused) {
      for (const listener of pauseListeners) listener(paused);
    },
  };
}

export default fakePortal;
