// The run as the server sees it: the same seed and inputs give the same state every time,
// random play never breaks the rules, and a recorded run replays to its own score.
import {
    checkDeterminism,
    createRecorder,
    fromRunRecord,
    fuzz,
    toRunRecord,
    verify,
} from "@karni/game/sim";
import { describe, expect, it } from "vitest";
import { runnerSim, type RunnerInput } from "../src/rules";

/** Jump every 70 ticks: a run that lasts a while on most seeds. */
const rhythm = (tick: number): RunnerInput => ({ jump: tick % 70 === 0, revive: false });

describe("the run on the simulation contract", () => {
    it("is deterministic: the same seed and inputs give the same hash at every check", () => {
        const hashes = checkDeterminism(runnerSim, { seed: 2026, ticks: 3000, input: rhythm, every: 100 });
        expect(hashes).toHaveLength(30);
    });

    it("lays the same track for the same seed, and another for another seed", () => {
        const a = createRecorder(runnerSim, { seed: 5 });
        const b = createRecorder(runnerSim, { seed: 5 });
        const c = createRecorder(runnerSim, { seed: 6 });
        expect(a.sim.state.track).toEqual(b.sim.state.track);
        expect(c.sim.state.track.islands).not.toEqual(a.sim.state.track.islands);
    });

    it("survives random inputs, continues included, and keeps its invariants", () => {
        const report = fuzz(runnerSim, { seed: 9, runs: 16, ticks: 2400, pastDone: true });
        expect(report.runs).toBe(16);
    });

    it("replays a recorded run, sent as the score's run, to its own score and hash", () => {
        const recorder = createRecorder(runnerSim, { seed: 314 });
        for (let tick = 0; tick < 4000 && !recorder.sim.done; tick += 1) recorder.step(rhythm(tick));
        if (recorder.sim.done) recorder.step({ jump: false, revive: true });
        for (let tick = 0; tick < 600 && !recorder.sim.done; tick += 1) recorder.step(rhythm(tick));
        const recording = recorder.finish();
        expect(recording.score).toBeGreaterThan(0);
        const run = toRunRecord(recording);
        expect(run.seed).toBe("314");
        const verdict = verify(runnerSim, fromRunRecord<RunnerInput>(run));
        expect(verdict.ok).toBe(true);
        // A run sent with a higher score than its inputs give is caught.
        const edited = fromRunRecord<RunnerInput>({ ...run, meta: { ...run.meta, score: recording.score + 50 } });
        expect(verify(runnerSim, edited).ok).toBe(false);
    });
});
