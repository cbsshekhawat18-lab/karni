import type { LoadResult, Save } from "../save/save";

export interface StoreOptions<T extends object> {
  /** The save layer the store keeps its state in: versions, migrations and a corrupt save are its job. */
  save: Save<T>;
  /**
   * Wait this long after a change before writing, so a slider drag is one
   * write. Default 250 ms. 0 writes at once.
   */
  debounceMs?: number;
  /** Write when the page is hidden or closed. Default true where there is a page. */
  flushOnHide?: boolean;
  /** What `reset` goes back to. Default: the save's own defaults, found by upgrading an empty object. */
  defaults?: () => T;
  /** Called when a write is refused (storage full or blocked). The state stays in memory. */
  onWriteError?(): void;
}

/** A small observable state kept in a {@link Save}: settings and progress. */
export interface Store<T extends object> {
  /** The current state. Treat it as read only: change it with `set` or `update`. */
  readonly state: Readonly<T>;
  /** How the save loaded: "new", "loaded", "migrated", "corrupt" or "newer". */
  readonly loaded: LoadResult<T>;
  /** Merge a patch into the state. */
  set(patch: Partial<T>): void;
  /** Change a copy of the state in place: `update((draft) => { draft.stars[id] = 3; })`. */
  update(change: (draft: T) => void): void;
  /** Call `listener` after every change. Returns the function that removes it. */
  subscribe(listener: (state: Readonly<T>, previous: Readonly<T>) => void): () => void;
  /** Go back to the save's defaults. */
  reset(): void;
  /** Write now, if a write is waiting. False when storage refused it. */
  flush(): boolean;
  destroy(): void;
}

function copy<T>(value: T): T {
  return typeof structuredClone === "function"
    ? structuredClone(value)
    : (JSON.parse(JSON.stringify(value)) as T);
}

/**
 * A store on the save layer: it loads once, notifies subscribers, and writes
 * after a short delay and again when the page is hidden. The state is plain
 * JSON, as the save layer needs.
 */
export function createStore<T extends object>(options: StoreOptions<T>): Store<T> {
  const { save } = options;
  const delay = options.debounceMs ?? 250;
  const loaded = save.load();
  let state: T = loaded.data;
  const listeners = new Set<(state: Readonly<T>, previous: Readonly<T>) => void>();
  let timer: ReturnType<typeof setTimeout> | null = null;
  let dirty = false;

  const flush = (): boolean => {
    if (timer !== null) clearTimeout(timer);
    timer = null;
    if (!dirty) return true;
    dirty = false;
    const ok = save.write(state);
    if (!ok) options.onWriteError?.();
    return ok;
  };

  const change = (next: T): void => {
    const previous = state;
    state = next;
    dirty = true;
    if (delay <= 0) flush();
    else if (timer === null) timer = setTimeout(flush, delay);
    for (const listener of [...listeners]) {
      try {
        listener(state, previous);
      } catch (error) {
        console.error("[karni-game] a store listener threw", error);
      }
    }
  };

  const onHide = (): void => {
    if (typeof document === "undefined" || document.visibilityState === "hidden") flush();
  };
  const hooked = (options.flushOnHide ?? true) && typeof window !== "undefined";
  if (hooked) {
    window.addEventListener("pagehide", flush);
    document.addEventListener("visibilitychange", onHide);
  }

  return {
    get state() {
      return state;
    },
    loaded,
    set: (patch) => change({ ...state, ...patch }),
    update(mutate) {
      const draft = copy(state);
      mutate(draft);
      change(draft);
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    reset: () => change(options.defaults ? options.defaults() : save.upgrade({}, save.version)),
    flush,
    destroy() {
      flush();
      listeners.clear();
      if (hooked) {
        window.removeEventListener("pagehide", flush);
        document.removeEventListener("visibilitychange", onHide);
      }
    },
  };
}
