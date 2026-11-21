/** The share of shake and particles kept when the player asks for less motion. */
export const REDUCED_MOTION = 0.25;

/**
 * True when the browser asks for less motion (the system setting behind
 * `prefers-reduced-motion`). A game's own setting should win over it: set
 * `camera.motion` and `particles.motion` from the settings screen.
 */
export function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/** The default motion scale: 1, or `REDUCED_MOTION` when the browser asks for less. */
export function motionScale(): number {
  return prefersReducedMotion() ? REDUCED_MOTION : 1;
}
