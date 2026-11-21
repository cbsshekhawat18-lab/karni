import { createEmitter } from "../internal/emitter";
import { createFixedStep, type FixedStep } from "./fixed-step";
import { createPauseReasons } from "./reasons";

export interface LoopOptions {
  /**
   * Advance the game by `dt` seconds. With `step` set it is called with the
   * fixed step (zero or more times a frame), otherwise once a frame with the
   * clamped frame time.
   */
  update(dt: number): void;
  /** Draw. `alpha` is the leftover fraction of a fixed step (0 without one). */
  render?(alpha: number, dt: number): void;
  /** Run `update` in fixed steps of this many seconds (1/60, 1/120). Omit for a variable step. */
  step?: number;
  /** The most fixed steps a frame runs. Default 5. */
  maxSteps?: number;
  /** The longest frame time, in seconds, after a stall or a slow frame. Default 0.05. */
  maxDt?: number;
  /**
   * Called at the end of every frame that ran `update`, and of every frame
   * while paused: clear input edge flags here. With `step`, a frame that ran
   * no step does not call it, so a press in that frame reaches the next step.
   */
  afterFrame?(): void;
  /** Keep calling `render` while paused, so a pause screen is drawn. Default true. */
  renderWhilePaused?: boolean;
  /** Game seconds per real second: 0.5 is slow motion. Default 1. See `Loop.timeScale`. */
  timeScale?: number;
  /**
   * A frame that throws is reported here and the loop keeps running, so one
   * bad frame never stops the game. Default: `console.error` for the first ten.
   */
  onError?(error: unknown, phase: "update" | "render" | "afterFrame"): void;
  /** The frame scheduler. Default `requestAnimationFrame`. */
  requestFrame?: (callback: (time: number) => void) => number;
  cancelFrame?: (handle: number) => void;
}

export interface LoopEvents {
  /** The loop became paused; the value is the first reason. */
  pause: string;
  /** The last pause reason was lifted. */
  resume: undefined;
}

/** A requestAnimationFrame loop with a dt clamp, an optional fixed step and named pauses. */
export interface Loop {
  start(): void;
  stop(): void;
  readonly running: boolean;
  readonly paused: boolean;
  /** Why the loop is paused: "hidden", "blur", "ad", "portal", or a game's own reason. */
  readonly pauseReasons: ReadonlySet<string>;
  /** Pause for a reason. The loop runs again once every reason is resumed. */
  pause(reason?: string): void;
  resume(reason?: string): void;
  /** Frames run since start. */
  readonly frame: number;
  /** The fixed-step accumulator, when `step` is set. */
  readonly fixed: FixedStep | null;
  /**
   * Game seconds per real second, from 0 (frozen) up: 0.5 is slow motion.
   * With a fixed step the step stays the same size and fewer steps run, so a
   * seeded simulation stays deterministic. `render` keeps the real frame time.
   */
  timeScale: number;
  /**
   * Freeze the game for `ms` real milliseconds (the pause on a hit): no
   * update runs, `render` goes on, and a press made meanwhile waits for the
   * first update after it. A second call keeps the longer of the two.
   */
  hitStop(ms: number): void;
  /** The hit-stop left, in milliseconds (0 when none). */
  readonly hitStopMs: number;
  /** Run one frame of `dt` seconds by hand: for tests and headless runs. */
  tick(dt: number): void;
  on<K extends keyof LoopEvents>(event: K, listener: (value: LoopEvents[K]) => void): () => void;
}

export function createLoop(options: LoopOptions): Loop {
  const maxDt = options.maxDt ?? 0.05;
  const fixed = options.step
    ? createFixedStep({ step: options.step, maxSteps: options.maxSteps })
    : null;
  const renderWhilePaused = options.renderWhilePaused ?? true;
  const requestFrame =
    options.requestFrame ?? ((callback: (time: number) => void) => requestAnimationFrame(callback));
  const cancelFrame = options.cancelFrame ?? ((handle: number) => cancelAnimationFrame(handle));
  const events = createEmitter<LoopEvents>();
  let reported = 0;
  const onError =
    options.onError ??
    ((error: unknown, phase: string) => {
      if (reported >= 10) return;
      reported += 1;
      console.error(`[karni-game] the ${phase} of a frame threw`, error);
    });

  const pauses = createPauseReasons(
    (reason) => events.emit("pause", reason),
    () => {
      // The time spent paused is not game time.
      last = null;
      fixed?.reset();
      events.emit("resume", undefined);
    },
  );
  let handle: number | null = null;
  let last: number | null = null;
  let frame = 0;
  const scaleOf = (value: number): number => (Number.isFinite(value) ? Math.max(0, value) : 1);
  let timeScale = scaleOf(options.timeScale ?? 1);
  /** Seconds of hit-stop left. */
  let stopLeft = 0;

  const safely = (phase: "update" | "render" | "afterFrame", fn: () => void): void => {
    try {
      fn();
    } catch (error) {
      onError(error, phase);
    }
  };

  const tick = (dt: number): void => {
    frame += 1;
    const clamped = Math.min(Math.max(0, Number.isFinite(dt) ? dt : 0), maxDt);
    const paused = pauses.paused;
    // A hit-stop counts down in real time, and not while paused.
    const stopped = !paused && stopLeft > 0;
    if (stopped) stopLeft = Math.max(0, stopLeft - clamped);
    let alpha = 0;
    if (!paused) {
      const scaled = stopped ? 0 : clamped * timeScale;
      safely("update", () => {
        if (fixed) alpha = fixed.advance(scaled, options.update);
        else if (!stopped) options.update(scaled);
      });
    }
    if (options.render && (!paused || renderWhilePaused)) {
      const render = options.render;
      safely("render", () => render(alpha, paused ? 0 : clamped));
    }
    const stepped = paused || (fixed ? fixed.lastSteps > 0 : !stopped);
    if (options.afterFrame && stepped) safely("afterFrame", options.afterFrame);
  };

  const onFrame = (time: number): void => {
    if (handle === null) return;
    const dt = last === null ? 0 : (time - last) / 1000;
    last = time;
    tick(dt);
    if (handle !== null) handle = requestFrame(onFrame);
  };

  return {
    start() {
      if (handle !== null) return;
      last = null;
      handle = requestFrame(onFrame);
    },
    stop() {
      if (handle !== null) cancelFrame(handle);
      handle = null;
    },
    get running() {
      return handle !== null;
    },
    get paused() {
      return pauses.paused;
    },
    pauseReasons: pauses.reasons,
    pause(reason = "game") {
      pauses.pause(reason);
    },
    resume(reason = "game") {
      pauses.resume(reason);
    },
    get frame() {
      return frame;
    },
    get timeScale() {
      return timeScale;
    },
    set timeScale(value: number) {
      timeScale = scaleOf(value);
    },
    hitStop(ms) {
      if (Number.isFinite(ms) && ms > 0) stopLeft = Math.max(stopLeft, ms / 1000);
    },
    get hitStopMs() {
      return stopLeft * 1000;
    },
    fixed,
    tick,
    on: events.on,
  };
}
