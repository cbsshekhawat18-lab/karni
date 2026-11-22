import { boxesOverlap, type Box } from "./shapes";

export interface TriggerHandlers<Z, B> {
  /** A body came into a zone this update. */
  enter?(zone: Z, body: B): void;
  /** A body is still in a zone. */
  stay?(zone: Z, body: B): void;
  /** A body left a zone (or the zone was removed while it was inside). */
  exit?(zone: Z, body: B): void;
  /** Whether a body is in a zone. Default: the boxes overlap. Pass your own for circles. */
  overlaps?(zone: Z, body: B): boolean;
}

/**
 * Zones that report bodies coming in and going out: coins, checkpoints, a
 * goal, water. `update` runs the tests and calls the handlers, once per
 * change, so a coin is taken once however long the player stands on it.
 */
export interface Triggers<Z, B> {
  add(zone: Z): void;
  /** Remove a zone, safe inside a handler. Bodies inside it get `exit`. */
  remove(zone: Z): void;
  has(zone: Z): boolean;
  /** Test one body or several against every zone. */
  update(bodies: B | readonly B[]): void;
  /** Is the body in the zone (as of the last update)? */
  inside(zone: Z, body: B): boolean;
  /** Drop a body from every zone without `exit` (it was removed from the game). */
  forget(body: B): void;
  /** Remove every zone, without `exit`. */
  clear(): void;
  readonly zones: readonly Z[];
}

export function createTriggers<Z extends object = Box, B extends object = Box>(
  handlers: TriggerHandlers<Z, B> = {},
): Triggers<Z, B> {
  const overlaps =
    handlers.overlaps ??
    ((zone: Z, body: B) => boxesOverlap(zone as unknown as Box, body as unknown as Box));
  const zones: Z[] = [];
  const insides = new Map<Z, Set<B>>();
  let updating = false;
  let removed = false;

  const test = (zone: Z, set: Set<B>, body: B): void => {
    const over = overlaps(zone, body);
    const was = set.has(body);
    if (over && !was) {
      set.add(body);
      handlers.enter?.(zone, body);
    } else if (over) {
      handlers.stay?.(zone, body);
    } else if (was) {
      set.delete(body);
      handlers.exit?.(zone, body);
    }
  };

  const compact = (): void => {
    let kept = 0;
    for (let i = 0; i < zones.length; i += 1) {
      const zone = zones[i] as Z;
      if (insides.has(zone)) zones[kept++] = zone;
    }
    zones.length = kept;
    removed = false;
  };

  return {
    add(zone) {
      if (insides.has(zone)) return;
      insides.set(zone, new Set());
      zones.push(zone);
    },
    remove(zone) {
      const set = insides.get(zone);
      if (!set) return;
      insides.delete(zone);
      removed = true;
      for (const body of set) handlers.exit?.(zone, body);
      if (!updating) compact();
    },
    has: (zone) => insides.has(zone),
    update(bodies) {
      updating = true;
      try {
        const count = zones.length;
        for (let i = 0; i < count; i += 1) {
          const zone = zones[i] as Z;
          const set = insides.get(zone);
          if (!set) continue;
          if (Array.isArray(bodies)) {
            const list = bodies as readonly B[];
            for (let j = 0; j < list.length; j += 1) {
              if (!insides.has(zone)) break;
              test(zone, set, list[j] as B);
            }
          } else {
            test(zone, set, bodies as B);
          }
        }
      } finally {
        updating = false;
        if (removed) compact();
      }
    },
    inside: (zone, body) => insides.get(zone)?.has(body) ?? false,
    forget(body) {
      for (const set of insides.values()) set.delete(body);
    },
    clear() {
      insides.clear();
      zones.length = 0;
    },
    zones,
  };
}
