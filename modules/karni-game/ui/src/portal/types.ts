import type { StorageLike } from "../save/types";

/** The two kinds of full-screen ad a portal shows. */
export type AdKind = "interstitial" | "rewarded";

/**
 * What one portal's SDK wrapper implements. Only `name` and `init` are
 * required: a missing method means the portal has no such call, and the
 * {@link Portal} built around the adapter treats it as unavailable.
 *
 * An adapter only translates calls. Timeouts, cooldowns, the gameplay
 * pairing, muting and error handling live in `createPortal`, so a new
 * adapter stays a page of code.
 */
export interface PortalAdapter {
  readonly name: string;
  /** Wait for the SDK and initialise it. Reject when the SDK is missing or refuses. */
  init(): Promise<void>;
  loadingStart?(): void;
  loadingFinished?(): void;
  gameplayStart?(): void;
  gameplayStop?(): void;
  /** A celebration moment (a level won, a record): some portals show an effect. */
  happyMoment?(): void;
  /**
   * Show an interstitial. Call `onStart` when the ad really starts, if the SDK
   * says so. Resolve when the break is over, whether an ad showed or not.
   */
  interstitial?(onStart: () => void, placement: string): Promise<void>;
  /**
   * Show a rewarded ad. Resolve true only on the SDK's completed event: a
   * dismissed, failed or unfilled ad resolves false.
   */
  rewarded?(onStart: () => void, placement: string): Promise<boolean>;
  /** The portal's own mute setting. Calls `listener` with the current value and every change. */
  onMute?(listener: (muted: boolean) => void): () => void;
  /** The portal asks the game to pause or resume outside an ad call. */
  onPause?(listener: (paused: boolean) => void): () => void;
  /** The portal's data module, when it has one (a localStorage-shaped store). */
  storage?(): StorageLike | null;
  hasAdblock?(): Promise<boolean>;
}

/** What `Portal.interstitial()` reports. */
export type InterstitialOutcome =
  /** An ad played. */
  | "shown"
  /** The break ran but the SDK showed nothing (frequency rules, no fill). */
  | "skipped"
  /** Less than the cooldown passed since the last ad. Nothing was asked of the SDK. */
  | "cooldown"
  /** Another ad is playing. */
  | "busy"
  /** No SDK, the SDK failed to start, or the portal has no interstitials. */
  | "unavailable"
  /** The SDK threw or the break timed out. */
  | "error";

export interface PortalEvents {
  /** The SDK is ready (fires once, possibly after `init()` timed out). */
  ready: undefined;
  /** An ad break begins: mute and pause now. */
  adstart: AdKind;
  /** The ad break is over: unmute and resume. */
  adend: { kind: AdKind; outcome: InterstitialOutcome | "rewarded" | "not-rewarded" };
  /** The portal's mute setting changed. */
  mute: boolean;
  /** The portal asked the game to pause (true) or resume (false). */
  pause: boolean;
  /** A call into the SDK threw; the game carried on. */
  error: { where: string; error: unknown };
}

export interface PortalOptions {
  /** How long `init()` waits for the SDK before the game boots without it. Default 5000 ms. */
  initTimeoutMs?: number;
  /** An ad break that has not ended after this long is given up. Default 90000 ms. */
  adTimeoutMs?: number;
  /** The shortest time between two interstitials. Default 60000 ms. */
  interstitialCooldownMs?: number;
  /** No interstitial before this long after the portal was created. Default 0. */
  firstInterstitialAfterMs?: number;
  /** A completed rewarded ad restarts the interstitial cooldown. Default true. */
  rewardedResetsCooldown?: boolean;
  /** The clock, in milliseconds. Default `Date.now`. */
  now?: () => number;
}

export type PortalStatus = "idle" | "loading" | "ready" | "failed";

/**
 * The guarded portal a game talks to. Every method is safe to call at any
 * time: before the SDK is ready (calls are replayed when it is), without an
 * SDK (they do nothing), and during an ad (they wait for it to end).
 */
export interface Portal {
  readonly name: string;
  readonly status: PortalStatus;
  /** An ad is playing now. */
  readonly adPlaying: AdKind | null;
  /** The portal's mute setting. */
  readonly muted: boolean;
  /** Start the SDK. Resolves true when ready, false on failure or timeout. Never rejects. */
  init(): Promise<boolean>;
  loadingStart(): void;
  loadingFinished(): void;
  /** The player is playing. Paired with `gameplayStop`: repeated calls are sent once. */
  gameplayStart(): void;
  gameplayStop(): void;
  happyMoment(): void;
  /** Can an interstitial be asked for now (ready, no ad playing, cooldown passed)? */
  canShowInterstitial(): boolean;
  interstitial(placement?: string): Promise<InterstitialOutcome>;
  /**
   * Can a rewarded ad be asked for now (ready, an SDK with rewarded ads, no ad
   * playing)? A game shows its "watch an ad" button only then.
   */
  canShowRewarded(): boolean;
  /** True only when the SDK reports the ad as watched to the end. */
  rewarded(placement?: string): Promise<boolean>;
  /** The portal's data module, or null. */
  storage(): StorageLike | null;
  hasAdblock(): Promise<boolean>;
  on<K extends keyof PortalEvents>(
    event: K,
    listener: (value: PortalEvents[K]) => void,
  ): () => void;
}
