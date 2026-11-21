// The rules play headless: no page, no clock, no network. `npm test` runs these.
import { createRng } from "@karni/game";
import { describe, expect, it } from "vitest";
import { createRun, replay, runScore, stepRun } from "../src/rules";

/** A run played with the given jumps, to its end or `frames` steps. */
const play = (seed: number, jumpOn: (frame: number) => boolean, frames = 3_000) => {
    const run = createRun(seed);
    while (!run.over && run.frame < frames) stepRun(run, jumpOn(run.frame));
    return run;
};

describe("the rules of __GAME_TITLE__", () => {
    it("make the same world from the same seed", () => {
        expect(createRun(7).blocks).toEqual(createRun(7).blocks);
        expect(createRun(7).blocks).not.toEqual(createRun(8).blocks);
    });

    it("replay a run from its seed and input log to the same score", () => {
        const rng = createRng(99);
        const run = play(1234, () => rng.chance(0.05));
        const again = replay(run.seed, run.inputs);
        expect(again.frame).toBe(run.frame);
        expect(runScore(again)).toBe(runScore(run));
    });

    it("end a run that never jumps in the first gap", () => {
        const run = play(5, () => false);
        expect(run.over).toBe(true);
        expect(runScore(run)).toBeGreaterThan(0);
    });

    it("never throw or make NaN, whatever the player presses", () => {
        for (let seed = 1; seed <= 25; seed += 1) {
            const rng = createRng(seed * 31);
            const run = play(seed, () => rng.chance(0.3), 1_200);
            for (const value of [run.distance, run.y, run.vy, runScore(run)]) {
                expect(Number.isFinite(value), `seed ${seed}`).toBe(true);
            }
        }
    });
});
