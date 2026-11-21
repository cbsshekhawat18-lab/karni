import { createRng } from "../rng";
import { describePlain, findNonFinite } from "./hash";
import { createRecorder, replay, type Recording, type Sim, type SimDefinition } from "./sim";

/** Where test helpers report a failure. The message names the seed and tick to run again. */
export class SimTestError extends Error {
  override name: string = "SimTestError";
}

/** The input of every tick: a list (the idle input after its end) or a function of the tick. */
export type InputScript<State, Input, Event, Config> =
  readonly Input[] | ((tick: number, sim: Sim<State, Input, Event, Config>) => Input);

function inputOf<State, Input, Event, Config>(
  definition: SimDefinition<State, Input, Event, Config>,
  script: InputScript<State, Input, Event, Config> | undefined,
  tick: number,
  sim: Sim<State, Input, Event, Config>,
): Input {
  if (!script) return definition.idle;
  if (typeof script === "function") return script(tick, sim);
  return script[tick] ?? definition.idle;
}

export interface HeadlessOptions<State, Input, Event, Config> {
  seed: number | string;
  config?: Config;
  /** The most ticks to run. */
  ticks: number;
  /** The scripted input. Default: the idle input every tick. */
  input?: InputScript<State, Input, Event, Config>;
  /** Stop at the first tick the rules say the run is done. Default true. */
  stopWhenDone?: boolean;
  build?: string;
  meta?: Record<string, unknown>;
}

export interface HeadlessResult<State, Input, Event, Config> {
  sim: Sim<State, Input, Event, Config>;
  recording: Recording<Input, Config>;
  /** Every event of the run, in order. */
  events: Event[];
  ticks: number;
  score: number;
  hash: string;
  done: boolean;
}

/** Run a game's rules with no page for up to `ticks` ticks of scripted input. */
export function runHeadless<State, Input, Event = string, Config = undefined>(
  definition: SimDefinition<State, Input, Event, Config>,
  options: HeadlessOptions<State, Input, Event, Config>,
): HeadlessResult<State, Input, Event, Config> {
  const recorder = createRecorder(definition, options);
  const { sim } = recorder;
  const events: Event[] = [];
  const stopWhenDone = options.stopWhenDone ?? true;
  for (let tick = 0; tick < options.ticks; tick += 1) {
    if (stopWhenDone && sim.done) break;
    events.push(...recorder.step(inputOf(definition, options.input, tick, sim)));
  }
  return {
    sim,
    recording: recorder.finish(),
    events,
    ticks: sim.tick,
    score: sim.score,
    hash: sim.hash(),
    done: sim.done,
  };
}

export interface DeterminismOptions<State, Input, Event, Config> {
  seed: number | string;
  config?: Config;
  ticks: number;
  input?: InputScript<State, Input, Event, Config>;
  /** Hash every this many ticks. Default 1. */
  every?: number;
}

/**
 * Run the same seed and inputs three times (twice live, once as a replay of
 * the recording) and check every hash matches tick by tick. Throws a
 * `SimTestError` naming the first tick that differs. Returns the hashes.
 * This catches a clock, `Math.random`, state kept outside the sim, and a
 * step that depends on object identity.
 */
export function checkDeterminism<State, Input, Event = string, Config = undefined>(
  definition: SimDefinition<State, Input, Event, Config>,
  options: DeterminismOptions<State, Input, Event, Config>,
): string[] {
  const every = Math.max(1, Math.floor(options.every ?? 1));
  const live = (): { hashes: string[]; recording: Recording<Input, Config> } => {
    const recorder = createRecorder(definition, options);
    const hashes: string[] = [];
    for (let tick = 0; tick < options.ticks; tick += 1) {
      recorder.step(inputOf(definition, options.input, tick, recorder.sim));
      if ((tick + 1) % every === 0) hashes.push(recorder.sim.hash());
    }
    return { hashes, recording: recorder.finish() };
  };
  const first = live();
  const second = live();
  const replayed: string[] = [];
  replay(definition, first.recording, {
    onTick: (sim) => {
      if (sim.tick % every === 0) replayed.push(sim.hash());
    },
  });
  const compare = (name: string, other: string[]): void => {
    for (let index = 0; index < first.hashes.length; index += 1) {
      if (first.hashes[index] !== other[index]) {
        throw new SimTestError(
          `not deterministic: the ${name} differs at tick ${(index + 1) * every} ` +
            `(seed ${String(options.seed)}): ${String(first.hashes[index])} then ${String(other[index])}`,
        );
      }
    }
  };
  compare("second run", second.hashes);
  compare("replay", replayed);
  return first.hashes;
}

export interface FuzzOptions<State, Input, Event, Config> {
  /** Makes the sim seeds and the inputs. Default 1. */
  seed?: number | string;
  config?: Config;
  /** Runs, each with its own sim seed. Default 20. */
  runs?: number;
  /** Ticks per run. Default 600. */
  ticks?: number;
  /** Random input. Default the rules' own `randomInput`. */
  input?: (
    rng: ReturnType<typeof createRng>,
    tick: number,
    sim: Sim<State, Input, Event, Config>,
  ) => Input;
  /** Keep going after the rules say the run is done (a game that revives). Default false. */
  pastDone?: boolean;
}

export interface FuzzReport {
  runs: number;
  /** Ticks run over all runs. */
  ticks: number;
  /** The score each run ended with. */
  scores: number[];
}

/** A fuzz run that failed: the rules threw, made a number NaN or infinite, or broke an invariant. */
export class FuzzFailure<Input, Config = undefined> extends SimTestError {
  override name = "FuzzFailure";
  constructor(
    message: string,
    readonly seed: number,
    readonly tick: number,
    /** The recording up to the failure, to replay or to keep as a regression test. */
    readonly recording: Recording<Input, Config>,
  ) {
    super(message);
  }
}

/**
 * Feed random inputs to the rules for N ticks, several times over. Fails on
 * a throw, a NaN or infinite number in the state, state that is not plain
 * data, and any invariant the rules declare. The failure carries the seed,
 * the tick and the recording.
 */
export function fuzz<State, Input, Event = string, Config = undefined>(
  definition: SimDefinition<State, Input, Event, Config>,
  options: FuzzOptions<State, Input, Event, Config> = {},
): FuzzReport {
  const runs = options.runs ?? 20;
  const ticks = options.ticks ?? 600;
  const pick =
    options.input ??
    ((rng, tick, sim) => {
      if (!definition.randomInput)
        throw new SimTestError("fuzz needs `randomInput` in the rules, or the `input` option");
      return definition.randomInput(rng, sim.state, tick);
    });
  const seeds = createRng(options.seed ?? 1);
  const report: FuzzReport = { runs, ticks: 0, scores: [] };
  for (let run = 0; run < runs; run += 1) {
    const seed = seeds.int(0, 2 ** 31 - 1);
    const inputs = createRng(`input:${seed}`);
    const recorder = createRecorder(definition, { seed, config: options.config });
    const { sim } = recorder;
    const fail = (tick: number, why: string): never => {
      throw new FuzzFailure(
        `fuzz run ${run}, seed ${seed}, tick ${tick}: ${why}`,
        seed,
        tick,
        recorder.finish(),
      );
    };
    for (let tick = 0; tick < ticks; tick += 1) {
      if (!options.pastDone && sim.done) break;
      try {
        recorder.step(pick(inputs, tick, sim));
      } catch (error) {
        if (error instanceof SimTestError) throw error;
        fail(tick, `the rules threw ${error instanceof Error ? error.message : String(error)}`);
      }
      const plain = describePlain(sim.state);
      if (plain) fail(tick, plain);
      const bad = findNonFinite(sim.state);
      if (bad) fail(tick, bad);
      const broken = sim.failedInvariants();
      if (broken.length) fail(tick, `invariant broken: ${broken.join("; ")}`);
    }
    report.ticks += sim.tick;
    report.scores.push(sim.score);
  }
  return report;
}
