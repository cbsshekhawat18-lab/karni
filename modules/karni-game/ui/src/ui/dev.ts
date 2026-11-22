import type { Loop } from "../runtime/loop";
import { el } from "./dom";
import type { Ui } from "./ui";

declare const __KARNI_GAME_DEV__: boolean | undefined;

export interface DevOverlayOptions {
  loop: Pick<Loop, "fixed">;
  /** How many entities are alive: `() => entities.size`. */
  entities?: () => number;
  /**
   * Show it. Default: true only in `vite dev` (the preset's `__KARNI_GAME_DEV__`),
   * so a build never carries it. Pass true to look at a build.
   */
  enabled?: boolean;
  /** The frame scheduler and the clock, for tests. */
  requestFrame?: (callback: () => void) => number;
  cancelFrame?: (handle: number) => void;
  now?: () => number;
}

export interface DevOverlay {
  /** Null when it is off. */
  readonly element: HTMLElement | null;
  destroy(): void;
}

/**
 * Frame time, steps per frame and the entity count, in a corner. It does
 * nothing unless `enabled` or the build is a dev build.
 */
export function createDevOverlay(
  ui: Pick<Ui, "root" | "t">,
  options: DevOverlayOptions,
): DevOverlay {
  const enabled =
    options.enabled ?? (typeof __KARNI_GAME_DEV__ !== "undefined" && __KARNI_GAME_DEV__ === true);
  if (!enabled) return { element: null, destroy: () => undefined };
  const { t } = ui;
  const requestFrame = options.requestFrame ?? ((cb) => requestAnimationFrame(cb));
  const cancelFrame = options.cancelFrame ?? ((handle) => cancelAnimationFrame(handle));
  const now = options.now ?? (() => performance.now());
  // The overlay is for the developer: a screen reader skips it.
  const element = el("div", { class: "kg-dev", "aria-hidden": "true" });
  ui.root.appendChild(element);

  let handle = 0;
  let last = now();
  let since = last;
  let frames = 0;
  let slowest = 0;
  let steps = 0;
  const tick = (): void => {
    const at = now();
    const frame = at - last;
    last = at;
    frames += 1;
    slowest = Math.max(slowest, frame);
    steps = Math.max(steps, options.loop.fixed?.lastSteps ?? 1);
    if (at - since >= 250) {
      const average = (at - since) / frames;
      element.textContent =
        `${t("devFrame")} ${average.toFixed(1)} ms (max ${slowest.toFixed(1)})  ${Math.round(1000 / average)} fps\n` +
        `${t("devSteps")} ${steps}  ${t("devEntities")} ${options.entities?.() ?? 0}`;
      since = at;
      frames = 0;
      slowest = 0;
      steps = 0;
    }
    handle = requestFrame(tick);
  };
  handle = requestFrame(tick);
  return {
    element,
    destroy() {
      cancelFrame(handle);
      element.remove();
    },
  };
}
