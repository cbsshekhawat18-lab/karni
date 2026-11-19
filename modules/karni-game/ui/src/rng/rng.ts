/** A seeded random number generator: the same seed gives the same sequence on every device. */
export interface Rng {
  /** The seed this generator started from, as a 32-bit unsigned number. */
  readonly seed: number;
  /** A float in [0, 1). */
  next(): number;
  /** A whole number from `min` to `max`, both included. */
  int(min: number, max: number): number;
  /** A float in [min, max). */
  float(min: number, max: number): number;
  /** True with probability `p`. */
  chance(p: number): boolean;
  /** One item. Throws on an empty list. */
  pick<T>(items: readonly T[]): T;
  /** Shuffle `items` in place (Fisher-Yates) and return it. */
  shuffle<T>(items: T[]): T[];
  /** A separate generator derived from this seed and a label: one stream per system. */
  fork(label: string | number): Rng;
  /** The internal state, to resume the exact sequence later (`createRng(seed).restore(state)`). */
  state(): number;
  restore(state: number): Rng;
}

/** A 32-bit hash of a string (FNV-1a), for turning text into a seed. */
export function hashSeed(text: string): number {
  let hash = 0x811c9dc5;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

const toSeed = (seed: number | string): number =>
  typeof seed === "string" ? hashSeed(seed) : Math.floor(Math.abs(seed)) >>> 0;

/**
 * A generator on mulberry32: small, fast and good enough for gameplay. Use a
 * number or any text (a share code, a date) as the seed. Never use it for
 * secrets.
 */
export function createRng(seed: number | string): Rng {
  const start = toSeed(seed);
  let a = start;
  const next = (): number => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const rng: Rng = {
    seed: start,
    next,
    int(min, max) {
      const low = Math.ceil(Math.min(min, max));
      const high = Math.floor(Math.max(min, max));
      return low + Math.floor(next() * (high - low + 1));
    },
    float: (min, max) => min + next() * (max - min),
    chance: (p) => next() < p,
    pick(items) {
      if (items.length === 0) throw new Error("rng.pick: the list is empty");
      return items[Math.floor(next() * items.length)] as (typeof items)[number];
    },
    shuffle(items) {
      for (let index = items.length - 1; index > 0; index -= 1) {
        const other = Math.floor(next() * (index + 1));
        const held = items[index] as (typeof items)[number];
        items[index] = items[other] as (typeof items)[number];
        items[other] = held;
      }
      return items;
    },
    fork: (label) => createRng(hashSeed(`${start}:${label}`)),
    state: () => a,
    restore(state) {
      a = state >>> 0;
      return rng;
    },
  };
  return rng;
}
