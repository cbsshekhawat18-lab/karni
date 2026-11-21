import { linear, type Ease } from "./ease";

type Same<X, Y, A, B> = (<V>() => V extends X ? 1 : 2) extends <V>() => V extends Y ? 1 : 2 ? A : B;

/** The writable number properties of `T`: what a tween can move (not a read-only count). */
export type NumberKeys<T> = {
  [K in keyof T]-?: T[K] extends number
    ? Same<{ [Q in K]: T[K] }, { -readonly [Q in K]: T[K] }, K, never>
    : never;
}[keyof T];

export interface TweenOptions<T> {
  /** Default `linear`. Pass any export of the easing set, or a function of your own. */
  ease?: Ease;
  /** Seconds before it starts. The start values are read when it starts. Default 0. */
  delay?: number;
  /** Times to play again after the first. `Infinity` for ever. Default 0. */
  repeat?: number;
  /** Play every other run backwards (there and back). Default false. */
  yoyo?: boolean;
  /** After every change. */
  onUpdate?(target: T): void;
  /** Once at the end (never for a cancelled tween or one that repeats for ever). */
  onDone?(target: T): void;
}

/** A running tween. */
export interface Tween {
  readonly done: boolean;
  /** Stop where it is. `onDone` does not run. */
  cancel(): void;
}

/** A list of tweens on the game clock: `update(dt)` in the game's update moves them all. */
export interface Tweens {
  /** Move number properties of `target` to the given values over `seconds`. */
  to<T extends object>(
    target: T,
    values: Partial<Record<NumberKeys<T>, number>>,
    seconds: number,
    options?: TweenOptions<T>,
  ): Tween;
  /** Wait `seconds` on the game clock, then call `then`: a timer that slows with the game. */
  wait(seconds: number, then: () => void): Tween;
  update(dt: number): void;
  /** Cancel every tween of `target` (a thing removed from the game). */
  cancelOf(target: object): void;
  clear(): void;
  /** Tweens running or waiting to start. */
  readonly size: number;
}

interface Running {
  target: Record<string, number>;
  keys: string[];
  from: number[];
  to: number[];
  seconds: number;
  delay: number;
  time: number;
  started: boolean;
  runs: number;
  backwards: boolean;
  done: boolean;
  ease: Ease;
  yoyo: boolean;
  repeat: number;
  onUpdate: ((target: object) => void) | undefined;
  onDone: ((target: object) => void) | undefined;
  handle: Tween;
}

function apply(run: Running, progress: number): void {
  const eased = run.ease(run.backwards ? 1 - progress : progress);
  for (let i = 0; i < run.keys.length; i += 1) {
    const from = run.from[i] as number;
    run.target[run.keys[i] as string] = from + ((run.to[i] as number) - from) * eased;
  }
}

function advance(run: Running, dt: number): void {
  let left = dt;
  if (!run.started) {
    if (run.delay > left) {
      run.delay -= left;
      return;
    }
    left -= run.delay;
    run.delay = 0;
    run.started = true;
    for (let i = 0; i < run.keys.length; i += 1)
      run.from[i] = run.target[run.keys[i] as string] ?? 0;
  }
  run.time += left;
  while (run.time >= run.seconds && !run.done) {
    if (run.runs >= run.repeat) {
      apply(run, 1);
      run.done = true;
      run.onUpdate?.(run.target);
      run.onDone?.(run.target);
      return;
    }
    run.runs += 1;
    run.time -= run.seconds;
    if (run.yoyo) run.backwards = !run.backwards;
    if (run.seconds <= 0) break;
  }
  if (run.done) return;
  apply(run, run.seconds > 0 ? run.time / run.seconds : 1);
  run.onUpdate?.(run.target);
}

/**
 * Tweens on the game clock. A tween reads its start values when it starts,
 * so tweens chained in `onDone` pick up where the last one ended. `update`
 * makes no garbage: new tweens allocate, running ones do not.
 */
export function createTweens(): Tweens {
  const list: Running[] = [];
  let updating = false;

  const add = (run: Running): Tween => {
    list.push(run);
    return run.handle;
  };

  const make = (
    target: object,
    keys: string[],
    to: number[],
    seconds: number,
    options: TweenOptions<object>,
  ): Running => {
    const run: Running = {
      target: target as Record<string, number>,
      keys,
      from: keys.map(() => 0),
      to,
      seconds: Math.max(0, seconds),
      delay: Math.max(0, options.delay ?? 0),
      time: 0,
      started: false,
      runs: 0,
      backwards: false,
      done: false,
      ease: options.ease ?? linear,
      yoyo: options.yoyo ?? false,
      repeat: Math.max(0, options.repeat ?? 0),
      onUpdate: options.onUpdate,
      onDone: options.onDone,
      handle: {
        get done() {
          return run.done;
        },
        cancel() {
          run.done = true;
        },
      },
    };
    return run;
  };

  const compact = (): void => {
    let kept = 0;
    for (let i = 0; i < list.length; i += 1) {
      const run = list[i] as Running;
      if (!run.done) list[kept++] = run;
    }
    list.length = kept;
  };

  return {
    to(target, values, seconds, options = {}) {
      const keys = Object.keys(values);
      const to = keys.map((key) => Number((values as Record<string, number>)[key]));
      return add(make(target, keys, to, seconds, options as TweenOptions<object>));
    },
    wait(seconds, then) {
      return add(make({}, [], [], seconds, { onDone: then }));
    },
    update(dt) {
      if (!(dt > 0) || updating) return;
      updating = true;
      // Tweens added by a callback start on the next update.
      const count = list.length;
      try {
        for (let i = 0; i < count; i += 1) {
          const run = list[i] as Running;
          if (!run.done) advance(run, dt);
        }
      } finally {
        updating = false;
        compact();
      }
    },
    cancelOf(target) {
      for (let i = 0; i < list.length; i += 1) {
        const run = list[i] as Running;
        if (run.target === target) run.done = true;
      }
      if (!updating) compact();
    },
    clear() {
      for (let i = 0; i < list.length; i += 1) (list[i] as Running).done = true;
      if (!updating) list.length = 0;
    },
    get size() {
      let size = 0;
      for (let i = 0; i < list.length; i += 1) if (!(list[i] as Running).done) size += 1;
      return size;
    },
  };
}
