export interface Pausable {
  pause(reason: string): void;
  resume(reason: string): void;
}

export interface PauseOnHiddenOptions {
  /** Also pause when the window loses focus. Default true. */
  blur?: boolean;
  document?: Document;
  window?: Window;
}

/**
 * Pause `targets` (a loop, the audio) while the tab is hidden ("hidden") and,
 * unless `blur: false`, while the window has no focus ("blur"). Returns the
 * function that removes the listeners.
 */
export function pauseOnHidden(
  targets: Pausable | readonly Pausable[],
  options: PauseOnHiddenOptions = {},
): () => void {
  const list: readonly Pausable[] = Array.isArray(targets) ? targets : [targets as Pausable];
  const doc = options.document ?? document;
  const win = options.window ?? window;
  const set = (reason: string, paused: boolean): void => {
    for (const target of list) {
      if (paused) target.pause(reason);
      else target.resume(reason);
    }
  };
  const onVisibility = (): void => set("hidden", doc.visibilityState === "hidden");
  const onBlur = (): void => set("blur", true);
  const onFocus = (): void => set("blur", false);
  doc.addEventListener("visibilitychange", onVisibility);
  if (options.blur ?? true) {
    win.addEventListener("blur", onBlur);
    win.addEventListener("focus", onFocus);
  }
  if (doc.visibilityState === "hidden") onVisibility();
  return () => {
    doc.removeEventListener("visibilitychange", onVisibility);
    win.removeEventListener("blur", onBlur);
    win.removeEventListener("focus", onFocus);
  };
}
