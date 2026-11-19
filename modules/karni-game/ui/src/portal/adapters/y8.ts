import type { PortalAdapter } from "../types";

interface Y8BreakInfo {
  breakStatus?: string;
}

interface Y8AdBreak {
  type: "next" | "reward";
  name: string;
  beforeAd?: () => void;
  afterAd?: () => void;
  beforeReward?: (showAd: () => void) => void;
  adViewed?: () => void;
  adDismissed?: () => void;
  adBreakDone?: (info?: Y8BreakInfo) => void;
}

/** The part of the Y8 SDK instance (`y8.sdk()`) the adapter calls. */
export interface Y8Sdk {
  init(
    app: { appId: string; autoLogin?: boolean },
    ads?: { gameId: string; preloadAdBreaks?: string; sound?: string; onReady?: () => void },
  ): unknown;
  showAd(adBreak: Y8AdBreak): unknown;
}

interface Y8Window {
  y8?: { sdk(): Y8Sdk; emitReadyEvent?: () => void };
}

export interface Y8Options {
  /** The game's app id on Y8, from the project's config. Required. */
  appId: string;
  /** The game id that turns ads on, from the project's config. Without it there are no ads. */
  gameId?: string;
  /** Sign the player in to Y8 on start. Default true, as Y8's SDK does. */
  autoLogin?: boolean;
  /** Where to find the SDK instance. Default waits for the `y8sdk.ready` event. */
  sdk?: () => Y8Sdk | undefined;
}

/**
 * Y8 (the minimal SDK, version 2). Breaks follow the ad placement shape:
 * an interstitial is a "next" break and a rewarded ad a "reward" break,
 * which counts only when `adViewed` fires.
 */
export function y8(options: Y8Options): PortalAdapter {
  const win = globalThis as unknown as Y8Window;
  let sdk: Y8Sdk | undefined;

  const ready = (): Promise<Y8Sdk> => {
    const given = options.sdk?.();
    if (given) return Promise.resolve(given);
    return new Promise((resolve, reject) => {
      const onReady = (): void => {
        try {
          const instance = win.y8?.sdk();
          if (instance) resolve(instance);
          else reject(new Error("y8.sdk() gave nothing"));
        } catch (error) {
          reject(error instanceof Error ? error : new Error(String(error)));
        }
      };
      window.addEventListener("y8sdk.ready", onReady, { once: true });
      // The script is async: it may have loaded before this listener existed.
      win.y8?.emitReadyEvent?.();
    });
  };

  const showAd = (adBreak: Omit<Y8AdBreak, "adBreakDone">): Promise<Y8BreakInfo | undefined> =>
    new Promise((resolve, reject) => {
      if (!sdk) {
        reject(new Error("Y8 SDK is not ready"));
        return;
      }
      const result = sdk.showAd({ ...adBreak, adBreakDone: (info) => resolve(info) });
      if (result instanceof Promise) result.catch(reject);
    });

  return {
    name: "y8",
    async init() {
      if (!options.appId) throw new Error("y8 needs an appId from the project's config");
      sdk = await ready();
      const instance = sdk;
      const gameId = options.gameId;
      const app = { appId: options.appId, autoLogin: options.autoLogin ?? true };
      if (!gameId) {
        await instance.init(app);
        return;
      }
      await new Promise<void>((resolve, reject) => {
        const result = instance.init(app, {
          gameId,
          preloadAdBreaks: "on",
          sound: "on",
          onReady: () => resolve(),
        });
        if (result instanceof Promise) result.catch(reject);
      });
    },
    async interstitial(onStart, placement) {
      if (!options.gameId) return;
      await showAd({ type: "next", name: placement, beforeAd: onStart });
    },
    async rewarded(onStart, placement) {
      if (!options.gameId) return false;
      let viewed = false;
      const info = await showAd({
        type: "reward",
        name: placement,
        // The game asked for the ad after its own prompt, so it is shown at once.
        beforeReward: (show) => show(),
        beforeAd: onStart,
        adViewed: () => {
          viewed = true;
        },
      });
      return viewed || info?.breakStatus === "viewed";
    },
  };
}

export default y8;
