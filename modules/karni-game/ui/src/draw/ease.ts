/**
 * Easing functions: each maps progress from 0 to 1 onto eased progress. Each
 * is its own export, so a game bundles only the ones it uses.
 */
export type Ease = (t: number) => number;

export const linear: Ease = (t) => t;
export const inQuad: Ease = (t) => t * t;
export const outQuad: Ease = (t) => t * (2 - t);
export const inOutQuad: Ease = (t) => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2);
export const inCubic: Ease = (t) => t * t * t;
export const outCubic: Ease = (t) => 1 - (1 - t) ** 3;
export const inOutCubic: Ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);
export const inSine: Ease = (t) => 1 - Math.cos((t * Math.PI) / 2);
export const outSine: Ease = (t) => Math.sin((t * Math.PI) / 2);
export const inOutSine: Ease = (t) => -(Math.cos(Math.PI * t) - 1) / 2;
export const inExpo: Ease = (t) => (t <= 0 ? 0 : 2 ** (10 * t - 10));
export const outExpo: Ease = (t) => (t >= 1 ? 1 : 1 - 2 ** (-10 * t));

const BACK = 1.70158;
/** Pulls back a little, then goes. */
export const inBack: Ease = (t) => (BACK + 1) * t * t * t - BACK * t * t;
/** Overshoots a little, then settles: a pop-in. */
export const outBack: Ease = (t) => 1 + (BACK + 1) * (t - 1) ** 3 + BACK * (t - 1) ** 2;

/** Springs past the end and settles. */
export const outElastic: Ease = (t) =>
  t <= 0 ? 0 : t >= 1 ? 1 : 2 ** (-10 * t) * Math.sin((t * 10 - 0.75) * ((2 * Math.PI) / 3)) + 1;

/** Bounces on the end like a dropped ball. */
export const outBounce: Ease = (t) => {
  const n = 7.5625;
  const d = 2.75;
  if (t < 1 / d) return n * t * t;
  if (t < 2 / d) return n * (t - 1.5 / d) ** 2 + 0.75;
  if (t < 2.5 / d) return n * (t - 2.25 / d) ** 2 + 0.9375;
  return n * (t - 2.625 / d) ** 2 + 0.984375;
};

/**
 * Move `current` toward `target` by a share that does not depend on the
 * frame rate: `rate` is how quickly, per second (10 is quick). The damped
 * follow of a camera, a health bar, a cursor.
 */
export function damp(current: number, target: number, rate: number, dt: number): number {
  if (!(rate > 0) || !(dt > 0)) return rate > 0 ? current : target;
  return target + (current - target) * Math.exp(-rate * dt);
}

/** `a` to `b` by `t`. */
export function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}
