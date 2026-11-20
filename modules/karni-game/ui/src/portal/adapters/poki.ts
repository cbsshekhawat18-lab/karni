import { waitFor } from "../../internal/time";
import type { PortalAdapter } from "../types";

/** The part of the Poki SDK (v2) the adapter calls. */
export interface PokiSdk {
  init(): Promise<unknown>;
  gameLoadingFinished(): void;
  gameplayStart(): void;
  gameplayStop(): void;
  commercialBreak(onStart?: () => void): Promise<unknown>;
  rewardedBreak(onStart?: () => void): Promise<boolean>;
}

export interface PokiOptions {
  /** Where to find the SDK. Default `window.PokiSDK`, put there by the SDK's script tag. */
  sdk?: () => PokiSdk | undefined;
  /** How long to wait for the SDK object to appear. Default 3000 ms. */
  waitMs?: number;
}

/**
 * Poki. The SDK's script tag is in the page (the per-portal build adds it).
 * `rewardedBreak` resolves its own success flag: only `true` is a reward.
 */
export function poki(options: PokiOptions = {}): PortalAdapter {
  const find =
    options.sdk ?? (() => (globalThis as unknown as { PokiSDK?: PokiSdk }).PokiSDK ?? undefined);
  let sdk: PokiSdk | undefined;
  return {
    name: "poki",
    async init() {
      sdk = await waitFor(find, options.waitMs ?? 3000, "PokiSDK");
      await sdk.init();
    },
    loadingFinished: () => sdk?.gameLoadingFinished(),
    gameplayStart: () => sdk?.gameplayStart(),
    gameplayStop: () => sdk?.gameplayStop(),
    async interstitial(onStart) {
      await sdk?.commercialBreak(onStart);
    },
    async rewarded(onStart) {
      if (!sdk) return false;
      return (await sdk.rewardedBreak(onStart)) === true;
    },
  };
}

export default poki;
