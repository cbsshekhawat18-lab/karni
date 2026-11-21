/**
 * Crate Climb's rules: a level larger than the screen, crates and walls that
 * block, one-way ledges to jump through, gems and a checkpoint as trigger
 * zones, and a flag at the top. Pure code on @karni/game/collide: no page, no
 * clock, no random numbers, so a test plays it headless.
 */
import {
  boxCircleOverlap,
  createMove,
  createTriggers,
  moveBox,
  type Box,
  type Circle,
  type Solid,
  type Triggers,
} from "@karni/game/collide";

export const LEVEL = {
  width: 1600,
  height: 540,
  gravity: 1400,
  jumpSpeed: 520,
  runSpeed: 150,
  /** A landing faster than this is a hard one: the screen shakes and the game stops a beat. */
  hardLanding: 560,
  step: 1 / 120,
} as const;

export interface Gem extends Circle {
  taken: boolean;
}

export interface Player extends Box {
  vy: number;
  grounded: boolean;
  /** 1 facing right, -1 facing left. */
  facing: number;
  /** Running this step, for the animation. */
  running: boolean;
}

export type ClimbEvent =
  | { type: "jump" | "respawn" | "checkpoint" | "goal"; x: number; y: number }
  | { type: "land"; x: number; y: number; hard: boolean }
  | { type: "gem"; x: number; y: number; gem: Gem };

export interface ClimbInput {
  left: boolean;
  right: boolean;
  /** Went down this step. */
  jump: boolean;
  /** Held: drop through a ledge. */
  down: boolean;
}

export interface Climb {
  player: Player;
  solids: Solid[];
  gems: Gem[];
  taken: number;
  spawn: { x: number; y: number };
  done: boolean;
  time: number;
  /** The flag at the top, and the line that moves the spawn point forward. */
  goal: Box;
  checkpoint: Box;
  /** Gems are circle zones, the checkpoint and the flag box zones: each reports the player once. */
  pickups: Triggers<Gem, Player>;
  zones: Triggers<Box, Player>;
  /** The events of the step being run, which the zones' handlers add to. */
  events: ClimbEvent[];
}

const CRATE = 32;
const LEDGE = 8;

function crate(x: number, y: number): Solid {
  return { x, y, w: CRATE, h: CRATE };
}

function ledge(x: number, y: number, w: number): Solid {
  return { x, y, w, h: LEDGE, oneWay: true };
}

/** The level: the same every time, so the gems, the route and the tests agree. */
function solids(): Solid[] {
  return [
    { x: -20, y: 0, w: 20, h: LEVEL.height },
    { x: LEVEL.width, y: 0, w: 20, h: LEVEL.height },
    { x: 0, y: 500, w: 760, h: 40 },
    { x: 840, y: 500, w: 760, h: 40 },
    crate(420, 468),
    crate(452, 468),
    crate(452, 436),
    crate(1000, 468),
    crate(1000, 436),
    crate(1032, 468),
    ledge(520, 420, 110),
    ledge(680, 350, 100),
    ledge(850, 400, 100),
    ledge(980, 340, 110),
    ledge(1140, 280, 110),
    ledge(1300, 220, 100),
    { x: 1440, y: 200, w: 160, h: 16 },
  ];
}

const GEMS: readonly [number, number][] = [
  [150, 488],
  [300, 488],
  [468, 420],
  [575, 405],
  [730, 335],
  [800, 440],
  [900, 385],
  [1035, 325],
  [1195, 265],
  [1350, 205],
  [1500, 180],
];

export function createClimb(): Climb {
  const climb: Climb = {
    player: { x: 40, y: 480, w: 14, h: 20, vy: 0, grounded: true, facing: 1, running: false },
    solids: solids(),
    gems: GEMS.map(([x, y]) => ({ x, y, r: 7, taken: false })),
    taken: 0,
    spawn: { x: 40, y: 480 },
    done: false,
    time: 0,
    goal: { x: 1540, y: 150, w: 24, h: 50 },
    checkpoint: { x: 850, y: 300, w: 20, h: 200 },
    pickups: createTriggers<Gem, Player>({
      overlaps: (gem, player) => boxCircleOverlap(player, gem),
      enter(gem) {
        gem.taken = true;
        climb.taken += 1;
        climb.pickups.remove(gem);
        climb.events.push({ type: "gem", x: gem.x, y: gem.y, gem });
      },
    }),
    zones: createTriggers<Box, Player>({
      enter(zone, player) {
        if (zone === climb.checkpoint) {
          climb.spawn = { x: zone.x, y: 380 };
          climb.events.push({ type: "checkpoint", x: player.x, y: player.y });
        } else if (zone === climb.goal && !climb.done) {
          climb.done = true;
          climb.events.push({ type: "goal", x: zone.x, y: zone.y });
        }
      },
    }),
    events: [],
  };
  for (const gem of climb.gems) climb.pickups.add(gem);
  climb.zones.add(climb.checkpoint);
  climb.zones.add(climb.goal);
  return climb;
}

const moved = createMove();
/** Reused every step: options made once, not per call. */
const moveOptions = { dropThrough: false };

/** Advance one fixed step. The events say what the page should show and play. */
export function stepClimb(climb: Climb, input: ClimbInput, dt = LEVEL.step): ClimbEvent[] {
  const events: ClimbEvent[] = [];
  climb.events = events;
  const p = climb.player;
  climb.time += dt;
  const dir = climb.done ? 0 : (input.right ? 1 : 0) - (input.left ? 1 : 0);
  if (dir !== 0) p.facing = dir;
  p.running = dir !== 0 && p.grounded;
  if (input.jump && p.grounded && !climb.done) {
    p.vy = -LEVEL.jumpSpeed;
    p.grounded = false;
    events.push({ type: "jump", x: p.x + p.w / 2, y: p.y + p.h });
  }
  p.vy += LEVEL.gravity * dt;
  const falling = p.vy;
  const wasGrounded = p.grounded;
  moveOptions.dropThrough = input.down;
  moveBox(p, dir * LEVEL.runSpeed * dt, p.vy * dt, climb.solids, moveOptions, moved);
  p.grounded = moved.bottom;
  if (moved.bottom) {
    if (!wasGrounded) {
      events.push({
        type: "land",
        x: p.x + p.w / 2,
        y: p.y + p.h,
        hard: falling > LEVEL.hardLanding,
      });
    }
    p.vy = 0;
  }
  if (moved.top) p.vy = 0;
  climb.pickups.update(p);
  climb.zones.update(p);
  if (p.y > LEVEL.height + 40) {
    p.x = climb.spawn.x;
    p.y = climb.spawn.y;
    p.vy = 0;
    events.push({ type: "respawn", x: p.x + p.w / 2, y: p.y + p.h });
  }
  return events;
}
