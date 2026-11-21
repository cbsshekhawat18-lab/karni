/**
 * Block Hopper's rules: a block that runs and jumps across platforms. They
 * are a simulation of @karni/game/sim: plain state, one step per fixed tick,
 * the input as data and every random number from the sim's seeded streams.
 * Nothing here reads a clock, the page or the network (`karni-game
 * check-rules` and the tests check it), so a seed plus the input log replays
 * a run exactly.
 */
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

export interface Platform {
  x: number;
  y: number;
  w: number;
}

export interface Coin {
  x: number;
  y: number;
  taken: boolean;
}

export interface HopperInput {
  left: boolean;
  right: boolean;
  /** Jump went down this step. */
  jump: boolean;
  /** The player watched a rewarded ad: bring a fallen player back. */
  revive: boolean;
}

export interface Hopper {
  x: number;
  y: number;
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
    const platform = { x: hopper.edge + gap, y, w };
    hopper.platforms.push(platform);
    if (rng.chance(0.6)) {
      hopper.pickups.push({ x: platform.x + w / 2, y: y - 40, taken: false });
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

function step(hopper: Hopper, input: HopperInput, ctx: SimContext<HopperEvent>): void {
  if (!hopper.alive) {
    // A rewarded continue is an input too, so a run that used it still replays.
    if (input.revive) revive(hopper);
    return;
  }
  const dt = ctx.dt;
  hopper.time += dt;
  const dir = (input.right ? 1 : 0) - (input.left ? 1 : 0);
  hopper.x += dir * WORLD.runSpeed * dt;
  if (input.jump && hopper.grounded) {
    hopper.vy = -WORLD.jumpSpeed;
    hopper.grounded = false;
    ctx.emit("jump");
  }
  hopper.vy += WORLD.gravity * dt;
  const before = hopper.y;
  hopper.y += hopper.vy * dt;
  const wasGrounded = hopper.grounded;
  hopper.grounded = false;
  for (const platform of hopper.platforms) {
    const over = hopper.x + WORLD.size > platform.x && hopper.x < platform.x + platform.w;
    const feet = hopper.y + WORLD.size;
    if (over && hopper.vy >= 0 && before + WORLD.size <= platform.y + 0.5 && feet >= platform.y) {
      hopper.y = platform.y - WORLD.size;
      hopper.vy = 0;
      hopper.grounded = true;
      if (!wasGrounded) ctx.emit("land");
      break;
    }
  }
  for (const coin of hopper.pickups) {
    if (
      !coin.taken &&
      Math.abs(coin.x - (hopper.x + WORLD.size / 2)) < 16 &&
      Math.abs(coin.y - (hopper.y + WORLD.size / 2)) < 18
    ) {
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
    const start: Platform = { x: 0, y: 200, w: 200 };
    const hopper: Hopper = {
      x: 60,
      y: start.y - WORLD.size,
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
