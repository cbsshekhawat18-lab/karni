/**
 * Block Hopper's rules: a block that runs and jumps across platforms. Pure
 * code, no page, so the tests play it headless and a seed plus the input log
 * replays a run exactly.
 */
import { createRng, type Rng } from "@karni/game";
import {
  boxCircleOverlap,
  createMove,
  moveBox,
  type Circle,
  type Solid,
} from "@karni/game/collide";

export const WORLD = {
  width: 480,
  height: 270,
  gravity: 1700,
  jumpSpeed: 640,
  runSpeed: 200,
  size: 18,
  /** The fixed step, in seconds. */
  step: 1 / 120,
} as const;

/** A ledge the block jumps up through and lands on. */
export interface Platform extends Solid {
  oneWay: true;
}

/** A coin is a circle around its centre. */
export interface Coin extends Circle {
  taken: boolean;
}

/** How thick a platform is. */
const LEDGE = 8;

export interface HopperInput {
  left: boolean;
  right: boolean;
  /** Jump went down this step. */
  jump: boolean;
}

export interface Hopper {
  seed: number;
  /** The block is a box: the mover moves it in place. */
  x: number;
  y: number;
  w: number;
  h: number;
  vy: number;
  grounded: boolean;
  alive: boolean;
  /** Farthest x reached. */
  farthest: number;
  coins: number;
  time: number;
  platforms: Platform[];
  pickups: Coin[];
  /** Where the next platform starts. */
  edge: number;
  rng: Rng;
}

export type HopperEvent = "jump" | "land" | "coin" | "fall";

export function createHopper(seed: number): Hopper {
  const start: Platform = { x: 0, y: 200, w: 200, h: LEDGE, oneWay: true };
  const hopper: Hopper = {
    seed,
    x: 60,
    y: start.y - WORLD.size,
    w: WORLD.size,
    h: WORLD.size,
    vy: 0,
    grounded: true,
    alive: true,
    farthest: 60,
    coins: 0,
    time: 0,
    platforms: [start],
    pickups: [],
    edge: start.x + start.w,
    rng: createRng(seed).fork("platforms"),
  };
  extend(hopper, WORLD.width * 2);
  return hopper;
}

/** Lay platforms ahead of the player, within jumping reach. */
function extend(hopper: Hopper, until: number): void {
  while (hopper.edge < until) {
    const last = hopper.platforms[hopper.platforms.length - 1];
    const gap = hopper.rng.int(40, 110);
    const w = hopper.rng.int(60, 160);
    const y = Math.min(240, Math.max(110, (last?.y ?? 200) + hopper.rng.int(-50, 40)));
    const platform: Platform = { x: hopper.edge + gap, y, w, h: LEDGE, oneWay: true };
    hopper.platforms.push(platform);
    if (hopper.rng.chance(0.6)) {
      hopper.pickups.push({ x: platform.x + w / 2, y: y - 40, r: 8, taken: false });
    }
    hopper.edge = platform.x + w;
  }
}

/** The score: distance in tenths of a block, and ten points a coin. */
export function score(hopper: Hopper): number {
  return Math.floor((hopper.farthest - 60) / 10) + hopper.coins * 10;
}

/** The mover's result, reused every step. */
const moved = createMove<Platform>();

/** Advance one fixed step. */
export function stepHopper(hopper: Hopper, input: HopperInput, dt = WORLD.step): HopperEvent[] {
  if (!hopper.alive) return [];
  const events: HopperEvent[] = [];
  hopper.time += dt;
  const dir = (input.right ? 1 : 0) - (input.left ? 1 : 0);
  if (input.jump && hopper.grounded) {
    hopper.vy = -WORLD.jumpSpeed;
    hopper.grounded = false;
    events.push("jump");
  }
  hopper.vy += WORLD.gravity * dt;
  const wasGrounded = hopper.grounded;
  // Platforms are one-way: the block jumps up through them and lands on top.
  moveBox(hopper, dir * WORLD.runSpeed * dt, hopper.vy * dt, hopper.platforms, undefined, moved);
  hopper.grounded = moved.bottom;
  if (moved.bottom) {
    hopper.vy = 0;
    if (!wasGrounded) events.push("land");
  }
  for (const coin of hopper.pickups) {
    if (!coin.taken && boxCircleOverlap(hopper, coin)) {
      coin.taken = true;
      hopper.coins += 1;
      events.push("coin");
    }
  }
  hopper.farthest = Math.max(hopper.farthest, hopper.x);
  extend(hopper, hopper.x + WORLD.width * 2);
  if (hopper.y > WORLD.height + 60) {
    hopper.alive = false;
    events.push("fall");
  }
  return events;
}

/** Bring a fallen player back on the platform nearest behind, for a rewarded continue. */
export function revive(hopper: Hopper): void {
  const behind =
    [...hopper.platforms].reverse().find((p) => p.x <= hopper.farthest) ?? hopper.platforms[0];
  if (!behind) return;
  hopper.x = behind.x + 4;
  hopper.y = behind.y - WORLD.size;
  hopper.vy = 0;
  hopper.grounded = true;
  hopper.alive = true;
}
