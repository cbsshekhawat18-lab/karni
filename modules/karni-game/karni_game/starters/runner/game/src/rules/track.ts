/**
 * The endless track: islands, clouds, spikes and coins laid ahead of the
 * runner from the sim's seeded stream, so a seed always makes the same
 * track. Every gap is one the runner can clear at the speed it will have
 * there, so a run ends by a mistake, never by a track that cannot be run.
 */
import type { Rng } from "@karni/game/sim";
import { WORLD, jumpReach, speedAt } from "./world";

/** A cliff top the runner lands on. Solid from its top down: hitting its side stops the run. */
export interface Island {
    x: number;
    y: number;
    w: number;
    h: number;
}

/** A small cloud over a gap: the runner lands on it from above and jumps up through it. */
export interface Cloud {
    x: number;
    y: number;
    w: number;
    h: number;
    oneWay: true;
}

export interface Spike {
    x: number;
    y: number;
    w: number;
    h: number;
}

/** A coin is a circle around its centre. */
export interface Coin {
    x: number;
    y: number;
    r: number;
    taken: boolean;
}

export interface Track {
    islands: Island[];
    clouds: Cloud[];
    spikes: Spike[];
    coins: Coin[];
    /** Where the next gap starts. */
    edge: number;
    /** The top of the last island. */
    top: number;
}

const ISLAND_DEPTH = WORLD.height * 2;

export function startTrack(): Track {
    const first: Island = { x: -40, y: 200, w: 420, h: ISLAND_DEPTH };
    return { islands: [first], clouds: [], spikes: [], coins: [], edge: first.x + first.w, top: first.y };
}

/** How hard the track is at `x`, from 0 at the start to 1 at full speed. */
export function difficulty(x: number): number {
    return Math.min(1, Math.max(0, x / WORLD.fullSpeedAt));
}

/** Coins along the arc of a jump from (x, y) at `speed`. */
function coinArc(track: Track, x: number, y: number, speed: number, count: number): void {
    const air = (2 * WORLD.jumpSpeed) / WORLD.gravity;
    for (let i = 1; i <= count; i += 1) {
        const t = (air * i) / (count + 1);
        const height = WORLD.jumpSpeed * t - (WORLD.gravity * t * t) / 2;
        track.coins.push({ x: x + speed * t, y: y - height - 12, r: 5, taken: false });
    }
}

/** A row of coins over an island, clear of its spikes. */
function coinRow(track: Track, x: number, y: number, count: number): void {
    for (let i = 0; i < count; i += 1) track.coins.push({ x: x + i * 18, y: y - 16, r: 5, taken: false });
}

/** One gap and the island after it. */
function addStretch(track: Track, rng: Rng): void {
    const level = difficulty(track.edge);
    const speed = speedAt(track.edge);
    const reach = jumpReach(speed);
    // Most gaps take one jump. Past the first stretch some need the second jump in the air.
    const double = level > 0.25 && rng.chance(0.15 + level * 0.3);
    const rise = rng.int(-45, 55);
    const top = Math.min(WORLD.lowest, Math.max(WORLD.highest, track.top + rise));
    const climbing = top < track.top - 15;
    const longest = (double ? reach.double * 0.7 : reach.single * 0.7) * (climbing ? 0.75 : 1);
    const gap = rng.float(Math.max(30, longest * (0.35 + level * 0.3)), Math.max(40, longest));
    const width = rng.int(Math.round(150 - level * 70), Math.round(320 - level * 140));
    const island: Island = { x: track.edge + gap, y: top, w: width, h: ISLAND_DEPTH };

    if (gap > 70 && rng.chance(0.35)) {
        // A cloud halfway over a long gap, with coins on it: a place to land and jump again.
        const cloudW = rng.int(46, 70);
        const cloudX = track.edge + gap / 2 - cloudW / 2;
        const cloudY = Math.min(track.top, top) - rng.int(40, 70);
        track.clouds.push({ x: cloudX, y: cloudY, w: cloudW, h: 10, oneWay: true });
        coinRow(track, cloudX + 8, cloudY, Math.max(2, Math.floor(cloudW / 20)));
    } else if (rng.chance(0.6)) {
        coinArc(track, track.edge - 10, track.top, speed, double ? 4 : 3);
    }

    track.islands.push(island);
    // Spikes leave room to land before them and to jump after them.
    const room = 70 + speed * 0.25;
    if (width > room * 2 + 20 && rng.chance(0.25 + level * 0.5)) {
        const spikeW = rng.int(14, 14 + Math.round(level * 18));
        const spikeX = island.x + rng.float(room, width - room - spikeW);
        track.spikes.push({ x: spikeX, y: top - 12, w: spikeW, h: 12 });
        if (rng.chance(0.5)) coinArc(track, spikeX - speed * 0.3, top, speed, 3);
    } else if (rng.chance(0.4)) {
        coinRow(track, island.x + 30, top, rng.int(3, 5));
    }
    track.edge = island.x + island.w;
    track.top = top;
}

/** Lay the track up to `until`, and drop what is far behind `behind`. */
export function extendTrack(track: Track, rng: Rng, until: number, behind: number): void {
    while (track.edge < until) addStretch(track, rng);
    const kept = (item: { x: number; w: number }): boolean => item.x + item.w >= behind;
    if (track.islands.length > 1 && !kept(track.islands[0] as Island)) {
        track.islands = track.islands.filter(kept);
        track.clouds = track.clouds.filter(kept);
        track.spikes = track.spikes.filter(kept);
        track.coins = track.coins.filter((coin) => coin.x + coin.r >= behind);
    }
}
