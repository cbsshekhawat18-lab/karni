/**
 * @karni/game/sim: the simulation contract. A game's rules are pure state, a
 * step function over fixed ticks, inputs as data and a seeded generator, so a
 * run replays exactly from its seed and inputs. No dependency, tree-shaken,
 * and no Node API: it runs in the browser and in Node.
 */
export { createRecorder, createSim, defineSim, replay, verify } from "./sim";
export type {
  InitContext,
  Recorder,
  RecorderOptions,
  Recording,
  ReplayOptions,
  Sim,
  SimContext,
  SimDefinition,
  SimOptions,
  SimSpec,
  SimTarget,
  Verdict,
} from "./sim";
export { canonical, describePlain, findNonFinite, hashState, hashText } from "./hash";
export { fromRunRecord, toRunRecord } from "./run-record";
export { createSimLoop } from "./loop";
export type { SimLoopOptions } from "./loop";
export { FuzzFailure, SimTestError, checkDeterminism, fuzz, runHeadless } from "./testing";
export type {
  DeterminismOptions,
  FuzzOptions,
  FuzzReport,
  HeadlessOptions,
  HeadlessResult,
  InputScript,
} from "./testing";
export { checkPurity, findImpurities, formatImpurities } from "./purity";
export type { Impurity, PurityRule } from "./purity";
export type { Rng } from "../rng";
