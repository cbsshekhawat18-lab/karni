import type { Portal } from "../portal/types";
import { linkPortal, type MuteTarget } from "../portal/link";
import { createFixedStep, type FixedStep } from "../runtime/fixed-step";
import { pauseOnHidden } from "../runtime/pause";
import { createPauseReasons } from "../runtime/reasons";

/**
 * The parts of a PixiJS `Application` the adapter touches (v7 and v8): its
 * ticker. A real application fits as it is; nothing is imported from Pixi.
 */
export interface PixiAppLike {
  ticker: {
    add(listener: () => void): unknown;
    remove(listener: () => void): unknown;
    start(): void;
    stop(): void;
    /** Milliseconds since the last tick. */
    readonly deltaMS: number;
  };
}

export interface PixiOptions {
  /** Run `update` in fixed steps of this many seconds on Pixi's ticker. Omit `update` to skip it. */
  step?: number;
  maxSteps?: number;
  /** The longest tick, in seconds, after a stall. Default 0.05. */
  maxDt?: number;
  update?(dt: number): void;
  /** Called every tick after the steps, with the leftover fraction of a step. */
  render?(alpha: number): void;
  /**
   * Called at the end of every tick that ran a step (every tick without
   * `update`): the input's `endFrame`. A press in a tick with no step reaches
   * the next step.
   */
  afterTick?(): void;
  portal?: Portal;
  /** Muted during ads and by the portal's setting (the audio from `createAudio`). */
  audio?: MuteTarget & { pause?(reason: string): void; resume?(reason: string): void };
  /** Stop the ticker on a hidden tab and on blur. Default true. */
  pauseOnHidden?: boolean;
}

export interface PixiLink {
  pause(reason: string): void;
  resume(reason: string): void;
  readonly paused: boolean;
  readonly fixed: FixedStep | null;
  disconnect(): void;
}

/**
 * Run a PixiJS game on Karni's pieces: Pixi's ticker stays the loop, with an
 * optional fixed step on it, and it stops for a hidden tab, blur, ads and
 * portal pauses, each a reason of its own.
 */
export function connectPixi(app: PixiAppLike, options: PixiOptions = {}): PixiLink {
  const maxDt = options.maxDt ?? 0.05;
  const fixed = options.update
    ? createFixedStep({ step: options.step, maxSteps: options.maxSteps })
    : null;
  const pauses = createPauseReasons(
    () => app.ticker.stop(),
    () => {
      fixed?.reset();
      app.ticker.start();
    },
  );
  const tick = (): void => {
    const dt = Math.min(Math.max(0, app.ticker.deltaMS / 1000), maxDt);
    let alpha = 0;
    if (fixed && options.update) alpha = fixed.advance(dt, options.update);
    options.render?.(alpha);
    if (!fixed || fixed.lastSteps > 0) options.afterTick?.();
  };
  app.ticker.add(tick);
  const link: PixiLink = {
    pause: (reason) => void pauses.pause(reason),
    resume: (reason) => void pauses.resume(reason),
    get paused() {
      return pauses.paused;
    },
    fixed,
    disconnect() {
      app.ticker.remove(tick);
      for (const unsubscribe of off) unsubscribe();
    },
  };
  const off: (() => void)[] = [];
  if (options.pauseOnHidden ?? true) off.push(pauseOnHidden(link));
  if (options.portal) off.push(linkPortal(options.portal, { loop: link, audio: options.audio }));
  return link;
}
