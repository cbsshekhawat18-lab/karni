import * as React from "react";

/** How long a request may run before Karni shows progress (ms). */
export const SLOW_AFTER_MS = 500;

/**
 * True once `active` has stayed true for `delayMs` (default 500ms), false as
 * soon as it turns false. Show progress only for slow work, so a fast request
 * never flashes a spinner.
 */
export function useDelayedFlag(active: boolean, delayMs: number = SLOW_AFTER_MS): boolean {
  const [elapsed, setElapsed] = React.useState(false);
  React.useEffect(() => {
    if (!active) {
      setElapsed(false);
      return undefined;
    }
    const timer = setTimeout(() => setElapsed(true), delayMs);
    return () => clearTimeout(timer);
  }, [active, delayMs]);
  return active && elapsed;
}

function subscribeOnline(onChange: () => void): () => void {
  window.addEventListener("online", onChange);
  window.addEventListener("offline", onChange);
  return () => {
    window.removeEventListener("online", onChange);
    window.removeEventListener("offline", onChange);
  };
}

/** Returns whether the browser reports a network connection and re-renders when it changes. */
export function useOnlineStatus(): boolean {
  return React.useSyncExternalStore(
    subscribeOnline,
    () => navigator.onLine,
    () => true,
  );
}
