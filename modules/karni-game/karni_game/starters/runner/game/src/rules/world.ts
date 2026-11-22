/** The numbers of the game's world, in game units (the view is 480 by 270) and seconds. */
export const WORLD = {
    width: 480,
    height: 270,
    /** The fixed step: 120 ticks a second. */
    step: 1 / 120,
    gravity: 1600,
    jumpSpeed: 540,
    /** The second jump, in the air. */
    doubleSpeed: 470,
    startSpeed: 170,
    maxSpeed: 320,
    /** The distance at which the runner reaches its top speed. */
    fullSpeedAt: 14_000,
    /** Where the runner starts. */
    startX: 60,
    /** Island tops stay between these heights. */
    highest: 135,
    lowest: 228,
    /** A jump pressed this many ticks before landing still happens on landing. */
    bufferTicks: 12,
    /** A jump pressed this many ticks after running off an edge still counts as from the ground. */
    coyoteTicks: 9,
    /** Ticks the runner cannot be hurt after a continue. */
    shieldTicks: 240,
    /** Continues a run may use. */
    continues: 1,
    /** Points: one for each ten units run, and this many for a coin. */
    coinPoints: 5,
} as const;

/** The runner's speed at a distance along the track. */
export function speedAt(x: number): number {
    const share = Math.min(1, Math.max(0, (x - WORLD.startX) / WORLD.fullSpeedAt));
    return WORLD.startSpeed + (WORLD.maxSpeed - WORLD.startSpeed) * share;
}

/** How far one jump, and a jump with the second one at its top, carry the runner at `speed`. */
export function jumpReach(speed: number): { single: number; double: number } {
    const up = WORLD.jumpSpeed / WORLD.gravity;
    const second = WORLD.doubleSpeed / WORLD.gravity;
    return { single: speed * up * 2, double: speed * (up + second * 2) };
}
