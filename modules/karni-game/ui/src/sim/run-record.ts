import type { RunRecord } from "../client/types";
import type { Recording } from "./sim";

/**
 * The run of the score API (`docs/game-api.md`) holds a seed, a list of
 * `[number, string]` inputs and `duration_ms`. A recording fits it without a
 * server change: `inputs` becomes `[tick, JSON text of the input]` for the
 * ticks where the input changed, and the rest goes in `meta`.
 */
export function toRunRecord<Input, Config>(recording: Recording<Input, Config>): RunRecord {
  const meta: Record<string, unknown> = {
    ...recording.meta,
    karni_sim: recording.v,
    seed_kind: typeof recording.seed === "number" ? "number" : "text",
    dt: recording.dt,
    ticks: recording.ticks,
    hash: recording.hash,
    score: recording.score,
  };
  if (recording.config !== undefined) meta.config = recording.config;
  const run: RunRecord = {
    seed: String(recording.seed),
    inputs: recording.inputs.map(([tick, input]): [number, string] => [
      tick,
      JSON.stringify(input),
    ]),
    duration_ms: Math.round(recording.ticks * recording.dt * 1000),
    meta,
  };
  if (recording.build !== undefined) run.build = recording.build;
  return run;
}

/** Read a run stored by `toRunRecord` back into a recording. Throws on a run another tool wrote. */
export function fromRunRecord<Input, Config = undefined>(run: RunRecord): Recording<Input, Config> {
  const meta = run.meta ?? {};
  if (meta.karni_sim !== 1) throw new Error("fromRunRecord: this run was not made by karni sim");
  const { karni_sim, seed_kind, dt, ticks, hash, score, config, ...rest } = meta;
  if (typeof dt !== "number" || typeof ticks !== "number" || typeof hash !== "string")
    throw new Error("fromRunRecord: the run's meta lacks dt, ticks or hash");
  const recording: Recording<Input, Config> = {
    v: 1,
    seed: seed_kind === "number" ? Number(run.seed) : run.seed,
    dt,
    ticks,
    inputs: run.inputs.map(([tick, text]): [number, Input] => [tick, JSON.parse(text) as Input]),
    hash,
    score: typeof score === "number" ? score : 0,
  };
  if (config !== undefined) recording.config = config as Config;
  if (run.build !== undefined) recording.build = run.build;
  if (karni_sim === 1 && Object.keys(rest).length) recording.meta = rest;
  return recording;
}
