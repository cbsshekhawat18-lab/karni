import type { StorageLike } from "./types";

const PROBE_KEY = "__karni_game_probe__";

/** Can `storage` write, read back and remove a value? False for blocked or full storage. */
export function probeStorage(storage: StorageLike | null | undefined): boolean {
  if (!storage) return false;
  try {
    storage.setItem(PROBE_KEY, "1");
    const ok = storage.getItem(PROBE_KEY) === "1";
    storage.removeItem(PROBE_KEY);
    return ok;
  } catch {
    return false;
  }
}

/** A storage kept in memory: what a game uses when the browser's storage is blocked. */
export function memoryStorage(): StorageLike & { clear(): void } {
  const values = new Map<string, string>();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => void values.set(key, String(value)),
    removeItem: (key) => void values.delete(key),
    clear: () => values.clear(),
    get length() {
      return values.size;
    },
    key: (index) => [...values.keys()][index] ?? null,
  };
}

/** The browser's localStorage, or null where reading it throws (sandboxed frames, privacy modes). */
export function browserStorage(): StorageLike | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

export interface StorageOptions {
  /** Prefix of every key, so games on one domain never mix: "block-hopper" gives "block-hopper.save". */
  namespace: string;
  /** Where values go. Default localStorage when it passes the probe, else memory. */
  backend?: StorageLike | null;
  /**
   * A portal's data module (the portal's `storage()`): read first, written
   * with the backend, so progress follows the player on that portal.
   */
  portal?: StorageLike | null;
}

export interface GameStorage {
  /** Where values are kept: the browser's storage, or memory when it is blocked. */
  readonly kind: "local" | "memory";
  /** Values outlive the page (false for memory). */
  readonly persistent: boolean;
  readonly namespace: string;
  get(key: string): string | null;
  /** False when the value could not be kept (storage full or blocked). */
  set(key: string, value: string): boolean;
  remove(key: string): void;
  /** This namespace's keys, without the prefix. */
  keys(): string[];
  /** The parsed JSON value, or undefined when missing or not valid JSON. */
  getJson<T = unknown>(key: string): T | undefined;
  setJson(key: string, value: unknown): boolean;
}

/**
 * Namespaced storage that never blocks a boot: it probes the browser's
 * storage and falls back to memory, and no call throws.
 */
export function createStorage(options: StorageOptions): GameStorage {
  const candidate = options.backend === undefined ? browserStorage() : options.backend;
  const persistent = probeStorage(candidate);
  const backend: StorageLike = persistent && candidate ? candidate : memoryStorage();
  const portal = options.portal && probeStorage(options.portal) ? options.portal : null;
  const prefix = `${options.namespace}.`;
  const full = (key: string): string => prefix + key;

  const storage: GameStorage = {
    kind: persistent ? "local" : "memory",
    persistent,
    namespace: options.namespace,
    get(key) {
      try {
        return portal?.getItem(full(key)) ?? backend.getItem(full(key));
      } catch {
        return null;
      }
    },
    set(key, value) {
      let kept = false;
      try {
        backend.setItem(full(key), value);
        kept = true;
      } catch {
        kept = false;
      }
      try {
        portal?.setItem(full(key), value);
        if (portal) kept = true;
      } catch {
        // The portal's module refused (size limit): the local copy stands.
      }
      return kept;
    },
    remove(key) {
      try {
        backend.removeItem(full(key));
        portal?.removeItem(full(key));
      } catch {
        // Nothing to undo.
      }
    },
    keys() {
      const found: string[] = [];
      try {
        const length = backend.length ?? 0;
        for (let index = 0; index < length; index += 1) {
          const key = backend.key?.(index);
          if (key?.startsWith(prefix)) found.push(key.slice(prefix.length));
        }
      } catch {
        return found;
      }
      return found;
    },
    getJson<T>(key: string) {
      const raw = storage.get(key);
      if (raw === null) return undefined;
      try {
        return JSON.parse(raw) as T;
      } catch {
        return undefined;
      }
    },
    setJson(key, value) {
      try {
        return storage.set(key, JSON.stringify(value));
      } catch {
        return false;
      }
    },
  };
  return storage;
}
