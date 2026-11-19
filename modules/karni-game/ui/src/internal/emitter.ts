/** A small typed event emitter: `on` returns the function that removes the listener. */
export interface Emitter<Events extends object> {
  on<K extends keyof Events>(event: K, listener: (value: Events[K]) => void): () => void;
  emit<K extends keyof Events>(event: K, value: Events[K]): void;
  clear(): void;
}

export function createEmitter<Events extends object>(
  onError: (error: unknown) => void = () => undefined,
): Emitter<Events> {
  const listeners = new Map<keyof Events, Set<(value: never) => void>>();
  return {
    on(event, listener) {
      let set = listeners.get(event);
      if (!set) {
        set = new Set();
        listeners.set(event, set);
      }
      set.add(listener as (value: never) => void);
      return () => {
        set.delete(listener as (value: never) => void);
      };
    },
    emit(event, value) {
      for (const listener of [...(listeners.get(event) ?? [])]) {
        try {
          (listener as (value: Events[typeof event]) => void)(value);
        } catch (error) {
          // One broken listener never stops the others, or the game.
          onError(error);
        }
      }
    },
    clear() {
      listeners.clear();
    },
  };
}
