import { createRng, type Rng } from "../rng";
import { canonical, describePlain, hashState } from "./hash";

/** What `init` may use. */
export interface InitContext {
  readonly seed: number | string;
  /** The main random stream, shared by every tick. Its state is part of the hash. */
  readonly rng: Rng;
  /** A separate random stream per label (`stream("platforms")`), in the hash too. */
  stream(label: string): Rng;
  /** Seconds per tick. */
  readonly dt: number;
}

/** What one tick of `step` may use: no clock, no outside randomness, nothing else. */
export interface SimContext<Event> extends InitContext {
  /** The tick being run, from 0. */
  readonly tick: number;
  /** Report something that happened (a sound, a particle). Events are not part of the hash. */
  emit(event: Event): void;
}

/**
 * The rules of one game as data and pure functions. State is plain data
 * (objects, arrays, numbers, strings, booleans, null), so it can be hashed
 * and kept. Input is plain data too: one value per tick.
 */
export interface SimSpec<State, Input, Event = string, Config = undefined> {
  /** Seconds per tick. Default 1/60. The loop runs this step. */
  dt?: number;
  /** The input of a tick in which the player did nothing. */
  idle: Input;
  /** The state at tick 0. Draw every random number from `ctx`. */
  init(ctx: InitContext, config: Config): State;
  /**
   * Advance one tick. Change `state` in place and return nothing, or return
   * the next state. Read time from `ctx.dt` and randomness from `ctx`.
   */
  // `void`: a step that changes the state in place returns nothing.
  // eslint-disable-next-line @typescript-eslint/no-invalid-void-type
  step(state: State, input: Input, ctx: SimContext<Event>): State | void;
  /** True when the run is over. The driver decides what to do then. Default never. */
  done?(state: State): boolean;
  /** The score of the run so far. Default 0. */
  score?(state: State): number;
  /**
   * Facts that must hold after every tick: true when they do,
   * false or a text saying why when they do not. The fuzz helper checks them.
   */
  invariants?: Record<string, (state: State) => boolean | string>;
  /** A random input for the fuzz helper. */
  randomInput?(rng: Rng, state: State, tick: number): Input;
  /** What to hash instead of the whole state (drop caches, convert a Map). Default the state. */
  snapshot?(state: State): unknown;
}

export interface SimDefinition<State, Input, Event = string, Config = undefined> {
  readonly dt: number;
  readonly idle: Input;
  readonly init: SimSpec<State, Input, Event, Config>["init"];
  readonly step: SimSpec<State, Input, Event, Config>["step"];
  readonly done: (state: State) => boolean;
  readonly score: (state: State) => number;
  readonly invariants: Readonly<Record<string, (state: State) => boolean | string>>;
  readonly randomInput?: SimSpec<State, Input, Event, Config>["randomInput"];
  readonly snapshot: (state: State) => unknown;
}

/** Check a spec and fill its defaults. */
export function defineSim<State, Input, Event = string, Config = undefined>(
  spec: SimSpec<State, Input, Event, Config>,
): SimDefinition<State, Input, Event, Config> {
  const dt = spec.dt ?? 1 / 60;
  if (!(dt > 0) || !Number.isFinite(dt)) throw new Error("defineSim: dt must be above 0");
  const problem = describePlain(spec.idle, "idle");
  if (problem) throw new Error(`defineSim: ${problem}`);
  return Object.freeze({
    dt,
    idle: spec.idle,
    init: spec.init,
    step: spec.step,
    done: spec.done ?? (() => false),
    score: spec.score ?? (() => 0),
    invariants: spec.invariants ?? {},
    randomInput: spec.randomInput,
    snapshot: spec.snapshot ?? ((state: State) => state),
  });
}

/** What a driver needs to run a sim a tick at a time: a `Sim` or a `Recorder`. */
export interface SimTarget<Input, Event = string> {
  readonly dt: number;
  readonly done: boolean;
  /** Run one tick with the player's input (the idle input when omitted). Returns the tick's events. */
  step(input?: Input): readonly Event[];
}

export interface Sim<State, Input, Event = string, Config = undefined> extends SimTarget<
  Input,
  Event
> {
  readonly definition: SimDefinition<State, Input, Event, Config>;
  readonly seed: number | string;
  readonly config: Config;
  readonly state: State;
  /** Ticks run so far. */
  readonly tick: number;
  readonly score: number;
  /** The hash of the tick count, every random stream and the state: 16 hex digits. */
  hash(): string;
  /** The invariants that do not hold now, as `name: reason`. Empty when all hold. */
  failedInvariants(): string[];
}

export interface SimOptions<Config> {
  seed: number | string;
  config?: Config;
}

/** Start a run of a game's rules. The same seed and inputs always give the same run. */
export function createSim<State, Input, Event = string, Config = undefined>(
  definition: SimDefinition<State, Input, Event, Config>,
  options: SimOptions<Config>,
): Sim<State, Input, Event, Config> {
  const { seed } = options;
  const config = options.config as Config;
  const rng = createRng(seed);
  const streams = new Map<string, Rng>();
  const stream = (label: string): Rng => {
    let found = streams.get(label);
    if (!found) {
      found = createRng(seed).fork(label);
      streams.set(label, found);
    }
    return found;
  };
  let state = definition.init({ seed, rng, stream, dt: definition.dt }, config);
  let tick = 0;
  let events: Event[] = [];
  const context: SimContext<Event> = {
    seed,
    rng,
    stream,
    dt: definition.dt,
    get tick() {
      return tick;
    },
    emit: (event) => {
      events.push(event);
    },
  };

  const sim: Sim<State, Input, Event, Config> = {
    definition,
    seed,
    config,
    dt: definition.dt,
    get state() {
      return state;
    },
    get tick() {
      return tick;
    },
    get done() {
      return definition.done(state);
    },
    get score() {
      return definition.score(state);
    },
    step(input = definition.idle) {
      events = [];
      const next = definition.step(state, input, context);
      if (next !== undefined) state = next;
      tick += 1;
      return events;
    },
    hash() {
      const streamStates: Record<string, number> = {};
      for (const [label, item] of streams) streamStates[label] = item.state();
      return hashState({
        tick,
        rng: rng.state(),
        streams: streamStates,
        state: definition.snapshot(state),
      });
    },
    failedInvariants() {
      const failed: string[] = [];
      for (const [name, check] of Object.entries(definition.invariants)) {
        const result = check(state);
        if (result === false) failed.push(name);
        else if (typeof result === "string") failed.push(`${name}: ${result}`);
      }
      return failed;
    },
  };
  return sim;
}

/**
 * A finished or running play: everything needed to run it again and the
 * hash it must reach. `inputs` holds only the ticks where the input changed
 * (`[tick, input]`), starting from the idle input.
 */
export interface Recording<Input, Config = undefined> {
  /** The format version of this record. */
  v: 1;
  seed: number | string;
  config?: Config;
  /** Seconds per tick of the rules that made it. */
  dt: number;
  ticks: number;
  inputs: [number, Input][];
  /** The state hash after the last tick. */
  hash: string;
  score: number;
  build?: string;
  meta?: Record<string, unknown>;
}

export interface Recorder<State, Input, Event = string, Config = undefined> extends SimTarget<
  Input,
  Event
> {
  readonly sim: Sim<State, Input, Event, Config>;
  /** The recording so far (it can be taken more than once). */
  finish(): Recording<Input, Config>;
}

export interface RecorderOptions<Config> extends SimOptions<Config> {
  /** The game's build, kept in the recording for the server's staff. */
  build?: string;
  meta?: Record<string, unknown>;
}

/** Run a sim and record its seed and the ticks where the input changed. */
export function createRecorder<State, Input, Event = string, Config = undefined>(
  definition: SimDefinition<State, Input, Event, Config>,
  options: RecorderOptions<Config>,
): Recorder<State, Input, Event, Config> {
  const sim = createSim(definition, options);
  const inputs: [number, Input][] = [];
  let last = canonical(definition.idle);
  return {
    sim,
    dt: definition.dt,
    get done() {
      return sim.done;
    },
    step(input = definition.idle) {
      const text = canonical(input);
      if (text !== last) {
        inputs.push([sim.tick, JSON.parse(JSON.stringify(input)) as Input]);
        last = text;
      }
      return sim.step(input);
    },
    finish() {
      const recording: Recording<Input, Config> = {
        v: 1,
        seed: options.seed,
        dt: definition.dt,
        ticks: sim.tick,
        inputs: inputs.map(([tick, input]): [number, Input] => [tick, input]),
        hash: sim.hash(),
        score: sim.score,
      };
      if (options.config !== undefined) recording.config = options.config;
      if (options.build !== undefined) recording.build = options.build;
      if (options.meta !== undefined) recording.meta = options.meta;
      return recording;
    },
  };
}

export interface ReplayOptions<State, Input, Event, Config> {
  /** Stop after this many ticks (to watch a part). Default every tick of the recording. */
  until?: number;
  /** Called after each tick with the sim and the tick's events: draw it, or hash it. */
  onTick?(sim: Sim<State, Input, Event, Config>, events: readonly Event[]): void;
}

/** Run a recording again and return the sim at its end. Throws on a recording the rules cannot play. */
export function replay<State, Input, Event = string, Config = undefined>(
  definition: SimDefinition<State, Input, Event, Config>,
  recording: Recording<Input, Config>,
  options: ReplayOptions<State, Input, Event, Config> = {},
): Sim<State, Input, Event, Config> {
  if (recording.v !== 1)
    throw new Error(`replay: record version ${String(recording.v)} is unknown`);
  const sim = createSim(definition, { seed: recording.seed, config: recording.config });
  const limit = Math.min(options.until ?? recording.ticks, recording.ticks);
  let next = 0;
  let current = definition.idle;
  let previous = -1;
  for (let tick = 0; tick < limit; tick += 1) {
    while (recording.inputs[next] && (recording.inputs[next] as [number, Input])[0] <= tick) {
      const [at, input] = recording.inputs[next] as [number, Input];
      if (at <= previous) throw new Error("replay: the input ticks must rise");
      previous = at;
      current = input;
      next += 1;
    }
    const events = sim.step(current);
    options.onTick?.(sim, events);
  }
  return sim;
}

export interface Verdict {
  /** True when the replay reached the recorded hash and score. */
  ok: boolean;
  /** The hash the recording claims, and the one the replay reached. */
  expected: string;
  actual: string;
  expectedScore: number;
  actualScore: number;
  ticks: number;
  /** Why it is not ok, in one sentence. */
  reason?: string;
}

/**
 * Play a recording through the rules and check it reaches its hash and
 * score. A rule that throws, or a recording made by other rules (another dt),
 * is a verdict that is not ok, never an exception.
 */
export function verify<State, Input, Event = string, Config = undefined>(
  definition: SimDefinition<State, Input, Event, Config>,
  recording: Recording<Input, Config>,
): Verdict {
  const base = {
    expected: recording.hash,
    expectedScore: recording.score,
    ticks: recording.ticks,
  };
  if (recording.dt !== definition.dt) {
    return {
      ...base,
      ok: false,
      actual: "",
      actualScore: Number.NaN,
      reason: `the recording ran at dt ${recording.dt}, the rules at ${definition.dt}`,
    };
  }
  try {
    const sim = replay(definition, recording);
    const actual = sim.hash();
    const actualScore = sim.score;
    const verdict = { ...base, actual, actualScore };
    if (actual !== recording.hash)
      return { ...verdict, ok: false, reason: "the replay ends in another state" };
    if (actualScore !== recording.score)
      return { ...verdict, ok: false, reason: "the replay ends with another score" };
    return { ...verdict, ok: true };
  } catch (error) {
    return {
      ...base,
      ok: false,
      actual: "",
      actualScore: Number.NaN,
      reason: `the replay threw: ${error instanceof Error ? error.message : String(error)}`,
    };
  }
}
