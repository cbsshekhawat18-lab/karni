import { waitFor } from "../../internal/time";
import type { StorageLike } from "../../save/types";
import type { PortalAdapter } from "../types";

interface CrazySettings {
  muteAudio?: boolean;
}

interface CrazyAdCallbacks {
  adStarted?: () => void;
  adFinished?: () => void;
  adError?: (error: { code?: string; message?: string }) => void;
}

/** The part of the CrazyGames SDK (v3, `window.CrazyGames.SDK`) the adapter calls. */
export interface CrazyGamesSdk {
  init(): Promise<unknown>;
  environment?: string;
  game: {
    gameplayStart(): void;
    gameplayStop(): void;
    happytime(): void;
    loadingStart(): void;
    loadingStop(): void;
    settings?: CrazySettings;
    addSettingsChangeListener?(listener: (settings: CrazySettings) => void): void;
    removeSettingsChangeListener?(listener: (settings: CrazySettings) => void): void;
  };
  ad: {
    requestAd(type: "midgame" | "rewarded", callbacks: CrazyAdCallbacks): unknown;
    hasAdblock?(): Promise<boolean>;
  };
  data?: StorageLike;
}

export interface CrazyGamesOptions {
  /** Where to find the SDK. Default `window.CrazyGames.SDK`. */
  sdk?: () => CrazyGamesSdk | undefined;
  /** How long to wait for the SDK object to appear. Default 3000 ms. */
  waitMs?: number;
}

/**
 * CrazyGames (SDK v3). A rewarded ad counts only when the SDK calls
 * `adFinished`. The player's mute setting on the site arrives as the
 * portal's mute, and the data module is offered as the portal's storage.
 */
export function crazyGames(options: CrazyGamesOptions = {}): PortalAdapter {
  const find =
    options.sdk ??
    (() =>
      (globalThis as unknown as { CrazyGames?: { SDK?: CrazyGamesSdk } }).CrazyGames?.SDK ??
      undefined);
  let sdk: CrazyGamesSdk | undefined;

  const requestAd = (type: "midgame" | "rewarded", onStart: () => void): Promise<boolean> =>
    new Promise((resolve) => {
      const result = sdk?.ad.requestAd(type, {
        adStarted: onStart,
        adFinished: () => resolve(true),
        adError: () => resolve(false),
      });
      // Some SDK builds also return a promise that rejects on error.
      if (result instanceof Promise) result.catch(() => resolve(false));
      if (!sdk) resolve(false);
    });

  return {
    name: "crazygames",
    async init() {
      sdk = await waitFor(find, options.waitMs ?? 3000, "CrazyGames.SDK");
      await sdk.init();
      // Off CrazyGames' own domains the SDK is disabled and its calls throw.
      if (sdk.environment === "disabled") throw new Error("CrazyGames SDK is disabled here");
    },
    loadingStart: () => sdk?.game.loadingStart(),
    loadingFinished: () => sdk?.game.loadingStop(),
    gameplayStart: () => sdk?.game.gameplayStart(),
    gameplayStop: () => sdk?.game.gameplayStop(),
    happyMoment: () => sdk?.game.happytime(),
    async interstitial(onStart) {
      await requestAd("midgame", onStart);
    },
    rewarded: (onStart) => requestAd("rewarded", onStart),
    onMute(listener) {
      const game = sdk?.game;
      if (!game) return () => undefined;
      listener(game.settings?.muteAudio === true);
      const onChange = (settings: CrazySettings): void => listener(settings.muteAudio === true);
      game.addSettingsChangeListener?.(onChange);
      return () => game.removeSettingsChangeListener?.(onChange);
    },
    storage: () => sdk?.data ?? null,
    hasAdblock: async () => (await sdk?.ad.hasAdblock?.()) === true,
  };
}

export default crazyGames;
