/**
 * Block Hopper's rules: a block that runs and jumps across platforms. They
 * are a simulation of @karni/game/sim: plain state, one step per fixed tick,
 * the input as data and every random number from the sim's seeded streams.
 * Nothing here reads a clock, the page or the network (`karni-game
 * check-rules` and the tests check it), so a seed plus the input log replays
 * a run exactly.
 */
import {
  boxCircleOverlap,
  createMove,
  moveBox,
  type Circle,
  type Solid,
} from "@karni/game/collide";
import { defineSim, type Rng, type SimContext } from "@karni/game/sim";

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
  /** The player watched a rewarded ad: bring a fallen player back. */
  revive: boolean;
}

export interface Hopper {
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
}

export type HopperEvent = "jump" | "land" | "coin" | "fall";

/** Lay platforms ahead of the player, within jumping reach. */
function extend(hopper: Hopper, rng: Rng, until: number): void {
  while (hopper.edge < until) {
    const last = hopper.platforms[hopper.platforms.length - 1];
    const gap = rng.int(40, 110);
    const w = rng.int(60, 160);
    const y = Math.min(240, Math.max(110, (last?.y ?? 200) + rng.int(-50, 40)));
    const platform: Platform = { x: hopper.edge + gap, y, w, h: LEDGE, oneWay: true };
    hopper.platforms.push(platform);
    if (rng.chance(0.6)) {
      hopper.pickups.push({ x: platform.x + w / 2, y: y - 40, r: 8, taken: false });
    }
    hopper.edge = platform.x + w;
  }
}

/** Bring a fallen player back on the platform nearest behind. */
function revive(hopper: Hopper): void {
  const behind =
    [...hopper.platforms].reverse().find((p) => p.x <= hopper.farthest) ?? hopper.platforms[0];
  if (!behind) return;
  hopper.x = behind.x + 4;
  hopper.y = behind.y - WORLD.size;
  hopper.vy = 0;
  hopper.grounded = true;
  hopper.alive = true;
}

/** The score: distance in tenths of a block, and ten points a coin. */
export function score(hopper: Hopper): number {
  return Math.floor((hopper.farthest - 60) / 10) + hopper.coins * 10;
}

/** The mover's result, reused every step: it holds nothing from one step to the next. */
const moved = createMove<Platform>();

function step(hopper: Hopper, input: HopperInput, ctx: SimContext<HopperEvent>): void {
  if (!hopper.alive) {
    // A rewarded continue is an input too, so a run that used it still replays.
    if (input.revive) revive(hopper);
    return;
  }
  const dt = ctx.dt;
  hopper.time += dt;
  const dir = (input.right ? 1 : 0) - (input.left ? 1 : 0);
  if (input.jump && hopper.grounded) {
    hopper.vy = -WORLD.jumpSpeed;
    hopper.grounded = false;
    ctx.emit("jump");
  }
  hopper.vy += WORLD.gravity * dt;
  const wasGrounded = hopper.grounded;
  // Platforms are one-way: the block jumps up through them and lands on top.
  moveBox(hopper, dir * WORLD.runSpeed * dt, hopper.vy * dt, hopper.platforms, undefined, moved);
  hopper.grounded = moved.bottom;
  if (moved.bottom) {
    hopper.vy = 0;
    if (!wasGrounded) ctx.emit("land");
  }
  for (const coin of hopper.pickups) {
    if (!coin.taken && boxCircleOverlap(hopper, coin)) {
      coin.taken = true;
      hopper.coins += 1;
      ctx.emit("coin");
    }
  }
  hopper.farthest = Math.max(hopper.farthest, hopper.x);
  extend(hopper, ctx.stream("platforms"), hopper.x + WORLD.width * 2);
  if (hopper.y > WORLD.height + 60) {
    hopper.alive = false;
    ctx.emit("fall");
  }
}

export const hopperSim = defineSim<Hopper, HopperInput, HopperEvent>({
  dt: WORLD.step,
  idle: { left: false, right: false, jump: false, revive: false },
  init(ctx) {
    const start: Platform = { x: 0, y: 200, w: 200, h: LEDGE, oneWay: true };
    const hopper: Hopper = {
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
    };
    extend(hopper, ctx.stream("platforms"), WORLD.width * 2);
    return hopper;
  },
  step,
  done: (hopper) => !hopper.alive,
  score,
  invariants: {
    "stays above the void": (h) => h.y < WORLD.height + 200,
    "never goes back past the start": (h) => h.x > -1000,
    "keeps the platforms ahead": (h) => h.edge >= h.x,
    "counts the coins it took": (h) => h.coins === h.pickups.filter((c) => c.taken).length,
  },
  randomInput: (rng) => ({
    left: rng.chance(0.2),
    right: rng.chance(0.7),
    jump: rng.chance(0.05),
    revive: rng.chance(0.01),
  }),
});
