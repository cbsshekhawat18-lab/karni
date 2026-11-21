// The rules alone, with no page: the track, the jumps, the coins, the end of a run and a continue.
import { createSim, runHeadless, type Sim } from "@karni/game/sim";
import { describe, expect, it } from "vitest";
import {
    WORLD,
    distance,
    jumpReach,
    runnerSim,
    score,
    speedAt,
    type RunEvent,
    type RunState,
    type RunnerInput,
} from "../src/rules";

const idle: RunnerInput = { jump: false, revive: false };

/** A player who jumps just before every edge and before every spike, and twice over long gaps. */
function careful(sim: Sim<RunState, RunnerInput, RunEvent>): RunnerInput {
    const { runner, track } = sim.state;
    const under = track.islands.find((i) => i.x <= runner.x + runner.w && i.x + i.w >= runner.x);
    const next = track.islands.find((i) => i.x > runner.x + runner.w);
    const speed = speedAt(runner.x);
    if (runner.grounded && under) {
        const edgeAhead = under.x + under.w - (runner.x + runner.w);
        const spike = track.spikes.find((s) => s.x > runner.x && s.x - (runner.x + runner.w) < speed * 0.18);
        if (spike || edgeAhead < speed * 0.05) return { jump: true, revive: false };
    }
    if (!runner.grounded && runner.vy > 0 && runner.airJumps > 0 && next && runner.y > next.y - 40) {
        return { jump: true, revive: false };
    }
    return idle;
}

describe("the runner's rules", () => {
    it("starts on the first island, running, with nothing collected", () => {
        const sim = createSim(runnerSim, { seed: 1 });
        expect(sim.state.alive).toBe(true);
        expect(sim.state.runner.grounded).toBe(true);
        expect(score(sim.state)).toBe(0);
        sim.step(idle);
        expect(sim.state.runner.x).toBeGreaterThan(WORLD.startX);
    });

    it("lays only gaps a jump can clear at the speed the runner has there", () => {
        const sim = createSim(runnerSim, { seed: 77 });
        for (let tick = 0; tick < 60 * 120; tick += 1) {
            sim.step(careful(sim));
            if (!sim.state.alive) break;
        }
        const { islands } = sim.state.track;
        for (let i = 1; i < islands.length; i += 1) {
            const before = islands[i - 1];
            const after = islands[i];
            if (!before || !after) continue;
            const gap = after.x - (before.x + before.w);
            expect(gap).toBeLessThanOrEqual(jumpReach(speedAt(before.x + before.w)).double);
            expect(after.y).toBeGreaterThanOrEqual(WORLD.highest);
            expect(after.y).toBeLessThanOrEqual(WORLD.lowest);
        }
    });

    it("jumps from the ground, once more in the air, and no more until it lands", () => {
        const sim = createSim(runnerSim, { seed: 3 });
        const events = [...sim.step({ jump: true, revive: false })];
        expect(events).toContain("jump");
        for (let i = 0; i < 20; i += 1) sim.step(idle);
        events.push(...sim.step({ jump: true, revive: false }));
        expect(events).toContain("double");
        const rising = sim.state.runner.vy;
        sim.step({ jump: true, revive: false });
        expect(sim.state.runner.vy).toBeGreaterThan(rising); // the third press waits for the ground
    });

    it("runs faster the further it goes, up to its top speed", () => {
        expect(speedAt(WORLD.startX)).toBe(WORLD.startSpeed);
        expect(speedAt(WORLD.startX + WORLD.fullSpeedAt / 2)).toBeGreaterThan(WORLD.startSpeed);
        expect(speedAt(1e9)).toBe(WORLD.maxSpeed);
    });

    it("ends when the runner never jumps, and a continue carries on from the next island once", () => {
        const fallen = runHeadless(runnerSim, { seed: 11, ticks: 20 * 120 });
        expect(fallen.done).toBe(true);
        const sim = fallen.sim;
        expect(["fall", "spike"]).toContain(sim.state.ended);
        const reached = distance(sim.state);
        expect(sim.step({ jump: false, revive: true })).toContain("revive");
        expect(sim.state.alive).toBe(true);
        expect(sim.state.runner.shield).toBe(WORLD.shieldTicks);
        expect(distance(sim.state)).toBeGreaterThanOrEqual(reached);
        for (let i = 0; i < 30; i += 1) sim.step(idle);
        expect(sim.state.runner.grounded).toBe(true);
        while (sim.state.alive) sim.step(idle);
        // The run had its one continue: another one is refused.
        expect(sim.step({ jump: false, revive: true })).toEqual([]);
        expect(sim.state.alive).toBe(false);
    });

    it("scores the distance in tens and every coin, and a careful player gets far", () => {
        const sim = createSim(runnerSim, { seed: 42 });
        for (let tick = 0; tick < 40 * 120 && sim.state.alive; tick += 1) sim.step(careful(sim));
        expect(distance(sim.state)).toBeGreaterThan(1500);
        expect(score(sim.state)).toBe(
            Math.floor(distance(sim.state) / 10) + sim.state.coins * WORLD.coinPoints,
        );
    });
});
