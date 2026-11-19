import { loadScript } from "../script";
import { GAMEDISTRIBUTION_SDK_URL } from "../sdks";
import type { PortalAdapter } from "../types";

interface GdEvent {
  name: string;
  message?: string;
}

/** The part of the GameDistribution SDK (`window.gdsdk`) the adapter calls. */
export interface GameDistributionSdk {
  showAd(type?: string): Promise<unknown>;
  preloadAd?(type: string): Promise<unknown>;
}

interface GdWindow {
  GD_OPTIONS?: { gameId: string; onEvent: (event: GdEvent) => void };
  gdsdk?: GameDistributionSdk;
}

export interface GameDistributionOptions {
  /** The game's id on GameDistribution, from the project's config. Required. */
  gameId: string;
  /** Default the SDK address GameDistribution documents. */
  scriptUrl?: string;
  /** Default "gamedistribution-jssdk", the id the SDK's own snippet uses. */
  scriptId?: string;
  /**
   * How long after the ad's promise settles a late "watched" event still
   * counts. Default 300 ms.
   */
  rewardGraceMs?: number;
  /** Where to find the SDK once loaded. Default `window.gdsdk`. */
  sdk?: () => GameDistributionSdk | undefined;
}

/**
 * GameDistribution. The SDK reads `window.GD_OPTIONS` when it loads, so this
 * adapter sets it and then loads the script itself (the per-portal build
 * adds no tag). The SDK pauses and resumes the game with events: during an
 * ad those mark the ad's start, outside one they arrive as the portal's
 * pause. A rewarded ad counts only after `SDK_REWARDED_WATCH_COMPLETE`.
 */
export function gameDistribution(options: GameDistributionOptions): PortalAdapter {
  const win = globalThis as unknown as GdWindow;
  const find = options.sdk ?? (() => win.gdsdk);
  const pauseListeners = new Set<(paused: boolean) => void>();
  let inAd = false;
  let adStarted: (() => void) | null = null;
  let watched = false;

  const show = async (type: string | undefined, onStart: () => void): Promise<void> => {
    const sdk = find();
    if (!sdk) throw new Error("gdsdk is not on the page");
    inAd = true;
    adStarted = onStart;
    try {
      await sdk.showAd(type);
    } finally {
      inAd = false;
      adStarted = null;
    }
  };

  return {
    name: "gamedistribution",
    init() {
      if (!options.gameId) {
        return Promise.reject(
          new Error("gameDistribution needs a gameId from the project's config"),
        );
      }
      return new Promise<void>((resolve, reject) => {
        win.GD_OPTIONS = {
          gameId: options.gameId,
          onEvent(event) {
            switch (event.name) {
              case "SDK_READY":
                resolve();
                break;
              case "SDK_ERROR":
                reject(new Error(event.message ?? "GameDistribution SDK error"));
                break;
              case "SDK_GAME_PAUSE":
                if (inAd) adStarted?.();
                else for (const listener of pauseListeners) listener(true);
                break;
              case "SDK_GAME_START":
                if (!inAd) for (const listener of pauseListeners) listener(false);
                break;
              case "SDK_REWARDED_WATCH_COMPLETE":
                watched = true;
                break;
            }
          },
        };
        loadScript(options.scriptUrl ?? GAMEDISTRIBUTION_SDK_URL, {
          id: options.scriptId ?? "gamedistribution-jssdk",
        }).then(() => {
          // The script was already on the page and the SDK is up: no second SDK_READY comes.
          if (find()) resolve();
        }, reject);
      });
    },
    async interstitial(onStart) {
      await show(undefined, onStart);
    },
    async rewarded(onStart) {
      watched = false;
      try {
        await show("rewarded", onStart);
      } catch {
        return false;
      }
      if (!watched)
        await new Promise((resolve) => setTimeout(resolve, options.rewardGraceMs ?? 300));
      return watched;
    },
    onPause(listener) {
      pauseListeners.add(listener);
      return () => pauseListeners.delete(listener);
    },
  };
}

export default gameDistribution;
