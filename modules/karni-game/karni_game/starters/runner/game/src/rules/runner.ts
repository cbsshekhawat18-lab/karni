/**
 * The runner's rules: a simulation of @karni/game/sim. The state is plain
 * data, one step is one fixed tick, the input is data, and every random
 * number comes from the sim's seeded stream. Nothing here reads a clock, the
 * page or the network (`npm run check-rules` checks it), so a seed and the
 * input log replay a run exactly: the same seed is the same track for every
 * player, which is what the daily run and its board stand on.
 */
import { boxCircleOverlap, boxesOverlap, createMove, moveBox } from "@karni/game/collide";
import { defineSim, type SimContext } from "@karni/game/sim";
import { extendTrack, startTrack, type Track } from "./track";
import { WORLD, speedAt } from "./world";

export interface RunnerInput {
    /** Jump was pressed this tick (a tap, Space, the up arrow). */
    jump: boolean;
    /** The player watched a rewarded ad: carry on from the next island. */
    revive: boolean;
}

export interface Runner {
    x: number;
    y: number;
    w: number;
    h: number;
    vy: number;
    grounded: boolean;
    /** Jumps left before landing: 1 after a jump from the ground, then 0. */
    airJumps: number;
    /** Ticks since the runner left the ground. */
    airborne: number;
    /** Ticks a pressed jump still waits for the ground. */
    buffered: number;
    /** Ticks it cannot be hurt. */
    shield: number;
}

export interface RunState {
    runner: Runner;
    track: Track;
    alive: boolean;
    /** How the run ended: "fall" or "spike", or "" while it goes on. */
    ended: "" | "fall" | "spike";
    coins: number;
    continues: number;
    ticks: number;
}

export type RunEvent = "jump" | "double" | "land" | "coin" | "spike" | "fall" | "revive";

const HITBOX_INSET = 3;
/** The mover's result, reused each tick: it carries nothing from one tick to the next. */
const moved = createMove();

/** Whole units run so far. */
export function distance(state: RunState): number {
    return Math.max(0, Math.floor(state.runner.x - WORLD.startX));
}

/** The score: one point for each ten units run, and more for each coin. */
export function score(state: RunState): number {
    return Math.floor(distance(state) / 10) + state.coins * WORLD.coinPoints;
}

function jump(state: RunState, ctx: SimContext<RunEvent>): void {
    const runner = state.runner;
    const fromGround = runner.grounded || runner.airborne <= WORLD.coyoteTicks;
    if (fromGround && runner.vy >= 0) {
        runner.vy = -WORLD.jumpSpeed;
        runner.grounded = false;
        runner.airborne = WORLD.coyoteTicks + 1;
        runner.airJumps = 1;
        runner.buffered = 0;
        ctx.emit("jump");
    } else if (runner.airJumps > 0) {
        runner.vy = -WORLD.doubleSpeed;
        runner.airJumps = 0;
        runner.buffered = 0;
        ctx.emit("double");
    } else {
        runner.buffered = WORLD.bufferTicks;
    }
}

/** Put a fallen runner on the island ahead (or the one under it), with a short shield. */
function revive(state: RunState, ctx: SimContext<RunEvent>): void {
    const runner = state.runner;
    const islands = state.track.islands;
    const ahead = islands.find((island) => island.x + island.w > runner.x + 40) ?? islands.at(-1);
    if (!ahead) return;
    runner.x = Math.max(runner.x, ahead.x + 12);
    runner.y = ahead.y - runner.h;
    runner.vy = 0;
    runner.grounded = true;
    runner.airborne = 0;
    runner.airJumps = 0;
    runner.shield = WORLD.shieldTicks;
    state.track.spikes = state.track.spikes.filter((s) => s.x > runner.x + 160 || s.x + s.w < runner.x);
    state.alive = true;
    state.ended = "";
    state.continues += 1;
    ctx.emit("revive");
}

function step(state: RunState, input: RunnerInput, ctx: SimContext<RunEvent>): void {
    if (!state.alive) {
        // A continue is an input too, so a run that used one still replays.
        if (input.revive && state.continues < WORLD.continues) revive(state, ctx);
        return;
    }
    const runner = state.runner;
    const dt = ctx.dt;
    state.ticks += 1;
    if (runner.shield > 0) runner.shield -= 1;
    if (input.jump) jump(state, ctx);
    else if (runner.buffered > 0) runner.buffered -= 1;

    runner.vy += WORLD.gravity * dt;
    const wasGrounded = runner.grounded;
    const track = state.track;
    moveBox(runner, speedAt(runner.x) * dt, runner.vy * dt, [...track.islands, ...track.clouds], undefined, moved);
    runner.grounded = moved.bottom;
    if (moved.bottom) {
        runner.vy = 0;
        runner.airborne = 0;
        runner.airJumps = 0;
        if (!wasGrounded) {
            ctx.emit("land");
            if (runner.buffered > 0) jump(state, ctx);
        }
    } else {
        runner.airborne += 1;
        if (moved.top) runner.vy = Math.max(0, runner.vy);
    }

    for (const coin of track.coins) {
        if (!coin.taken && boxCircleOverlap(runner, coin)) {
            coin.taken = true;
            state.coins += 1;
            ctx.emit("coin");
        }
    }
    if (runner.shield === 0) {
        const body = {
            x: runner.x + HITBOX_INSET,
            y: runner.y + HITBOX_INSET,
            w: runner.w - HITBOX_INSET * 2,
            h: runner.h - HITBOX_INSET,
        };
        if (track.spikes.some((spike) => boxesOverlap(body, spike))) {
            state.alive = false;
            state.ended = "spike";
            ctx.emit("spike");
            return;
        }
    }
    if (runner.y > WORLD.height + 40) {
        state.alive = false;
        state.ended = "fall";
        ctx.emit("fall");
        return;
    }
    extendTrack(track, ctx.stream("track"), runner.x + WORLD.width * 2, runner.x - WORLD.width);
}

export const runnerSim = defineSim<RunState, RunnerInput, RunEvent>({
    dt: WORLD.step,
    idle: { jump: false, revive: false },
    init(ctx) {
        const track = startTrack();
        const first = track.islands[0];
        const top = first ? first.y : 200;
        const runner: Runner = {
            x: WORLD.startX,
            y: top - 18,
            w: 14,
            h: 18,
            vy: 0,
            grounded: true,
            airJumps: 0,
            airborne: 0,
            buffered: 0,
            shield: 0,
        };
        const state: RunState = { runner, track, alive: true, ended: "", coins: 0, continues: 0, ticks: 0 };
        extendTrack(track, ctx.stream("track"), runner.x + WORLD.width * 2, runner.x - WORLD.width);
        return state;
    },
    step,
    done: (state) => !state.alive,
    score,
    invariants: {
        "the runner's numbers are finite": (s) => Number.isFinite(s.runner.x + s.runner.y + s.runner.vy),
        "the track stays ahead of the runner": (s) => !s.alive || s.track.edge > s.runner.x,
        "the speed stays within its bounds": (s) => speedAt(s.runner.x) <= WORLD.maxSpeed,
        "coins and continues never go below zero": (s) => s.coins >= 0 && s.continues >= 0,
        "a run uses at most its continues": (s) => s.continues <= WORLD.continues,
    },
    randomInput: (rng) => ({ jump: rng.chance(0.04), revive: rng.chance(0.02) }),
});
