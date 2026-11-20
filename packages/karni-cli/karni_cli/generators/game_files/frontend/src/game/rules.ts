// The rules of __GAME_TITLE__, with no page: plain functions a test plays
// headless. The hopper runs on its own. A jump clears a gap, a coin is worth 10
// points, and the run ends in the first gap it falls into. A run is its seed and
// the frames the player jumped on, so the same two replay it exactly: that is
// the run a score carries to the server (docs/game.md, "Scores and leaderboards").
import { createRng } from "@karni/game";

/** The world in game units: the canvas fits it, letterboxed. */
export const WORLD = { width: 480, height: 270, floor: 210, hopperX: 80, step: 1 / 60 } as const;

const GRAVITY = 1400;
const JUMP = 520;
const SPEED = 140;
const SPEEDUP = 4;
const START = 520;
const BLOCKS = 240;

export interface Block {
    x: number;
    width: number;
}

export interface Coin {
    x: number;
    /** Height above the floor: 0 is on the block, higher needs a jump. */
    y: number;
    taken: boolean;
}

export interface Run {
    seed: number;
    frame: number;
    distance: number;
    /** The hopper's height above the floor. Below 0 it is falling into a gap. */
    y: number;
    vy: number;
    blocks: Block[];
    coins: Coin[];
    collected: number;
    /** The input log: each frame the hopper jumped on. */
    inputs: [number, string][];
    over: boolean;
}

/** A new run on the world its seed makes. The first block is long, so a run starts on solid ground. */
export function createRun(seed: number): Run {
    const rng = createRng(seed);
    const blocks: Block[] = [{ x: 0, width: START }];
    const coins: Coin[] = [0, 1, 2].map((n) => ({ x: 200 + n * 90, y: 0, taken: false }));
    let x = START;
    for (let index = 0; index < BLOCKS; index += 1) {
        x += rng.int(50, 90 + Math.min(40, index));
        const width = rng.int(120, 320);
        blocks.push({ x, width });
        for (let n = rng.int(0, 3); n > 0; n -= 1) {
            coins.push({ x: x + 20 + n * 40, y: rng.chance(0.5) ? 0 : 70, taken: false });
        }
        x += width;
    }
    return { seed, frame: 0, distance: 0, y: 0, vy: 0, blocks, coins, collected: 0, inputs: [], over: false };
}

/** Where the hopper stands in the world. */
export const hopperAt = (run: Run): number => run.distance + WORLD.hopperX;

const onBlock = (run: Run): boolean => {
    const at = hopperAt(run);
    return run.blocks.some((block) => block.x <= at + 6 && at - 6 <= block.x + block.width);
};

/** One fixed step (WORLD.step) of the run. `jump` is the jump button pressed this step. */
export function stepRun(run: Run, jump: boolean): Run {
    if (run.over) return run;
    const dt = WORLD.step;
    const standing = run.y === 0 && onBlock(run);
    if (jump && standing) {
        run.vy = JUMP;
        run.inputs.push([run.frame, "jump"]);
    }
    const before = run.y;
    if (!standing || run.vy > 0) {
        run.vy -= GRAVITY * dt;
        run.y += run.vy * dt;
    }
    run.distance += (SPEED + SPEEDUP * run.frame * dt) * dt;
    if (before >= 0 && run.y <= 0 && run.vy <= 0 && onBlock(run)) {
        run.y = 0;
        run.vy = 0;
    } else if (run.y === 0 && !onBlock(run)) {
        run.y = -0.01;
    }
    const at = hopperAt(run);
    for (const coin of run.coins) {
        if (!coin.taken && Math.abs(coin.x - at) < 12 && Math.abs(coin.y - run.y) < 24) {
            coin.taken = true;
            run.collected += 1;
        }
    }
    run.over = run.y < -80;
    run.frame += 1;
    return run;
}

/** The run's score: a point per 10 units travelled and 10 per coin. */
export const runScore = (run: Run): number => Math.floor(run.distance / 10) + run.collected * 10;

/** Play a run again from its seed and input log, as a check of its score would. */
export function replay(seed: number, inputs: readonly [number, string][], maxFrames = 36_000): Run {
    const run = createRun(seed);
    const jumps = new Set(inputs.map(([frame]) => frame));
    while (!run.over && run.frame < maxFrames) stepRun(run, jumps.has(run.frame));
    return run;
}
