export interface PoolOptions<T> {
  /** Make a new item. Called only when no free item is left, up to `max`. */
  create(): T;
  /** Clean an item as it goes back to the pool. */
  reset?(item: T): void;
  /** The most live items. `acquire` returns null past it. Default 1000. */
  max?: number;
  /** Items made up front, so the first frames make none. Default 0. */
  prefill?: number;
}

/**
 * A pool of reusable items: bullets, particles, floating text. Items are made
 * once and handed out again, so a frame that spawns and removes things makes
 * no garbage for the collector to stop the game for.
 */
export interface Pool<T> {
  /** A free item, or null when `max` items are live. It keeps the values it had. */
  acquire(): T | null;
  /** Give an item back. False when it was not live. Linear in the live count. */
  release(item: T): boolean;
  /**
   * Visit every live item in order and give back the ones `keep` returns
   * false for, in one pass with no allocation. Do not acquire or release
   * from inside `keep`.
   */
  retain(keep: (item: T) => boolean): void;
  /** Visit every live item in order. */
  forEach(visit: (item: T) => void): void;
  /** Give every live item back. */
  clear(): void;
  /** Live items. */
  readonly size: number;
  /** Items made so far, live and free. */
  readonly made: number;
  readonly max: number;
}

export function createPool<T>(options: PoolOptions<T>): Pool<T> {
  const max = Math.max(0, Math.floor(options.max ?? 1000));
  const reset = options.reset;
  // One array: [0, size) are live, [size, length) are free.
  const items: T[] = [];
  let size = 0;
  const prefill = Math.min(max, Math.max(0, Math.floor(options.prefill ?? 0)));
  for (let i = 0; i < prefill; i += 1) items.push(options.create());

  const swap = (i: number, j: number): void => {
    const a = items[i] as T;
    items[i] = items[j] as T;
    items[j] = a;
  };

  return {
    acquire() {
      if (size < items.length) {
        size += 1;
        return items[size - 1] as T;
      }
      if (items.length >= max) return null;
      const item = options.create();
      items.push(item);
      size += 1;
      return item;
    },
    release(item) {
      const index = items.indexOf(item);
      if (index < 0 || index >= size) return false;
      // Keep the live items in order: shift the rest down one place.
      for (let i = index; i < size - 1; i += 1) items[i] = items[i + 1] as T;
      items[size - 1] = item;
      size -= 1;
      reset?.(item);
      return true;
    },
    retain(keep) {
      let kept = 0;
      for (let i = 0; i < size; i += 1) {
        const item = items[i] as T;
        if (keep(item)) {
          if (i !== kept) swap(i, kept);
          kept += 1;
        } else {
          reset?.(item);
        }
      }
      size = kept;
    },
    forEach(visit) {
      for (let i = 0; i < size; i += 1) visit(items[i] as T);
    },
    clear() {
      if (reset) for (let i = 0; i < size; i += 1) reset(items[i] as T);
      size = 0;
    },
    get size() {
      return size;
    },
    get made() {
      return items.length;
    },
    max,
  };
}
