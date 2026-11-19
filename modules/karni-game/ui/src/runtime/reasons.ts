/** A set of pause reasons: paused while any reason is held. */
export interface PauseReasons {
  readonly paused: boolean;
  readonly reasons: ReadonlySet<string>;
  /** Hold a reason. True when this made the target pause. */
  pause(reason: string): boolean;
  /** Lift a reason. True when this was the last one, so the target runs again. */
  resume(reason: string): boolean;
}

/**
 * Pause reasons for any target (a loop, an engine's ticker, audio): it
 * pauses on the first reason and runs again only when every reason is
 * lifted, so an ad ending never unpauses a game the player paused.
 */
export function createPauseReasons(
  onPause: (reason: string) => void = () => undefined,
  onResume: () => void = () => undefined,
): PauseReasons {
  const reasons = new Set<string>();
  return {
    get paused() {
      return reasons.size > 0;
    },
    reasons,
    pause(reason) {
      const was = reasons.size > 0;
      reasons.add(reason);
      if (was) return false;
      onPause(reason);
      return true;
    },
    resume(reason) {
      if (!reasons.delete(reason) || reasons.size > 0) return false;
      onResume();
      return true;
    },
  };
}
