import { createLoop, type Loop, type LoopOptions } from "../runtime/loop";
import type { SimTarget } from "./sim";

export interface SimLoopOptions<Input, Event = string> extends Omit<
  LoopOptions,
  "update" | "step"
> {
  /**
   * The sim or recorder to run. A function is read at every step, so a game
   * can start a new run without making a new loop. Its `dt` is the loop's step
   * and must not change.
   */
  target: SimTarget<Input, Event> | (() => SimTarget<Input, Event>);
  /** The player's input for this tick: read the keys here. */
  input(): Input;
  /**
   * Runs on every fixed step, whether or not the sim runs: menus, mute keys.
   * `active` is read before it, so a screen change made here takes effect on
   * the next step.
   */
  beforeStep?(dt: number): void;
  /** Run the sim only while this is true (a play screen, not a menu). Default always. */
  active?(): boolean;
  /** The events of each tick: play a sound, start a particle. */
  onEvents?(events: readonly Event[]): void;
}

/**
 * A loop whose fixed step is the sim's `dt`. Each step reads the input, runs
 * one tick of the target and passes the tick's events on. Frame time, pauses
 * and the step cap are the loop's own.
 */
export function createSimLoop<Input, Event = string>(options: SimLoopOptions<Input, Event>): Loop {
  const { target, input, beforeStep, active, onEvents, ...rest } = options;
  const current = (): SimTarget<Input, Event> => (typeof target === "function" ? target() : target);
  const dt = current().dt;
  return createLoop({
    ...rest,
    step: dt,
    update(step) {
      const running = !active || active();
      beforeStep?.(step);
      if (!running) return;
      const sim = current();
      if (sim.dt !== dt) throw new Error(`createSimLoop: the sim's dt changed from ${dt}`);
      const events = sim.step(input());
      if (events.length) onEvents?.(events);
    },
  });
}
