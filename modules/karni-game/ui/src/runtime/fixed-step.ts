export interface FixedStepOptions {
  /** Seconds per step. Default 1/60. */
  step?: number;
  /** The most steps one frame may run. Default 5. */
  maxSteps?: number;
}

/** A fixed-step accumulator: the simulation advances in equal steps whatever the frame rate. */
export interface FixedStep {
  readonly step: number;
  readonly maxSteps: number;
  /** Simulated seconds thrown away because a frame needed more than `maxSteps` steps. */
  readonly dropped: number;
  /**
   * The steps the last `advance` ran. 0 on a frame shorter than a step (every
   * other frame on a 120 Hz screen with a step of 1/60): input edges made in
   * that frame must wait for the next step, not be cleared.
   */
  readonly lastSteps: number;
  /**
   * Add `dt` seconds and run `update(step)` as many whole steps as fit, at
   * most `maxSteps`. A longer backlog is dropped, so a slow device slows the
   * game down instead of falling further behind each frame. Returns the
   * fraction of a step left over, for interpolating the render.
   */
  advance(dt: number, update: (step: number) => void): number;
  reset(): void;
}

const EPSILON = 1e-9;

export function createFixedStep(options: FixedStepOptions = {}): FixedStep {
  const step = options.step ?? 1 / 60;
  const maxSteps = Math.max(1, Math.floor(options.maxSteps ?? 5));
  if (!(step > 0)) throw new Error("createFixedStep: step must be above 0");
  let accumulator = 0;
  let dropped = 0;
  let lastSteps = 0;
  return {
    step,
    maxSteps,
    get dropped() {
      return dropped;
    },
    get lastSteps() {
      return lastSteps;
    },
    advance(dt, update) {
      if (dt > 0 && Number.isFinite(dt)) accumulator += dt;
      let steps = 0;
      while (accumulator + EPSILON >= step && steps < maxSteps) {
        update(step);
        accumulator -= step;
        steps += 1;
      }
      if (accumulator + EPSILON >= step) {
        // The spiral-of-death guard: never carry a backlog into the next frame.
        dropped += accumulator;
        accumulator = 0;
      }
      lastSteps = steps;
      return Math.max(0, accumulator) / step;
    },
    reset() {
      accumulator = 0;
    },
  };
}
