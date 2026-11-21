import type { Box } from "./shapes";

/** A box that blocks movers. */
export interface Solid extends Box {
  /** Blocks only from above: a ledge a body jumps up through and lands on. */
  oneWay?: boolean;
}

/**
 * Your own broad phase: call `visit` for every solid that may touch `area`
 * (from a grid, a list per room). A plain array is checked whole.
 */
export type SolidQuery<S extends Solid> = (area: Box, visit: (solid: S) => void) => void;

export type Solids<S extends Solid> = readonly S[] | SolidQuery<S>;

/** What a move did. */
export interface Move<S extends Solid = Solid> {
  /** How far the body moved on each axis. */
  dx: number;
  dy: number;
  /** The body was stopped on that side (it touches a solid there). */
  left: boolean;
  right: boolean;
  top: boolean;
  /** Stopped from below: standing on the ground. */
  bottom: boolean;
  /** The solid that stopped it on each axis. */
  hitX: S | null;
  hitY: S | null;
}

export interface MoveOptions<S extends Solid> {
  /** Fall through one-way ledges this move (down pressed on a ledge). Default false. */
  dropThrough?: boolean;
  /** Solids this body ignores (its own team's walls). Must not call `moveBox`. */
  filter?(solid: S): boolean;
}

export function createMove<S extends Solid = Solid>(): Move<S> {
  return {
    dx: 0,
    dy: 0,
    left: false,
    right: false,
    top: false,
    bottom: false,
    hitX: null,
    hitY: null,
  };
}

const EPS = 1e-7;
const shared = createMove<Solid>();
const area: Box = { x: 0, y: 0, w: 0, h: 0 };
// The move in progress, read by the visitors so a query needs no new closure.
let body: Box = area;
let allowed = 0;
/** The move is toward +x (or +y): fixed for the sweep, while `allowed` shrinks to 0. */
let forward = true;
let hit: Solid | null = null;
let drop = false;
let filter: ((solid: Solid) => boolean) | undefined;

function visitX(solid: Solid): void {
  if (solid.oneWay || (solid as Box) === body) return;
  if (filter && !filter(solid)) return;
  if (!(body.y < solid.y + solid.h && body.y + body.h > solid.y)) return;
  if (forward) {
    const gap = solid.x - (body.x + body.w);
    if (gap >= -EPS && gap <= allowed) {
      allowed = gap > 0 ? gap : 0;
      hit = solid;
    }
  } else {
    const gap = solid.x + solid.w - body.x;
    if (gap <= EPS && gap >= allowed) {
      allowed = gap < 0 ? gap : 0;
      hit = solid;
    }
  }
}

function visitY(solid: Solid): void {
  if ((solid as Box) === body) return;
  if (solid.oneWay && (!forward || drop)) return;
  if (filter && !filter(solid)) return;
  if (!(body.x < solid.x + solid.w && body.x + body.w > solid.x)) return;
  if (forward) {
    // Only what is at or below the feet stops a fall, so a one-way ledge is passed from below.
    const gap = solid.y - (body.y + body.h);
    if (gap >= -EPS && gap <= allowed) {
      allowed = gap > 0 ? gap : 0;
      hit = solid;
    }
  } else {
    const gap = solid.y + solid.h - body.y;
    if (gap <= EPS && gap >= allowed) {
      allowed = gap < 0 ? gap : 0;
      hit = solid;
    }
  }
}

function sweep<S extends Solid>(solids: Solids<S>, visit: (solid: Solid) => void): void {
  if (typeof solids === "function") {
    solids(area, visit as (solid: S) => void);
    return;
  }
  for (let i = 0; i < solids.length; i += 1) visit(solids[i] as S);
}

/**
 * Move a box by dx, dy against solid boxes: first along x, then along y, each
 * stopped at the first solid in the way, so it slides along walls and floors
 * and never passes through a thin solid however fast it goes. One-way solids
 * stop it only from above. A solid it already overlaps does not stop it, so
 * a body pushed inside one walks out.
 *
 * The body's x and y are changed in place. The result is `out`, or one object
 * shared by every call that does not pass its own: copy what you keep.
 */
export function moveBox<S extends Solid>(
  mover: Box,
  dx: number,
  dy: number,
  solids: Solids<S>,
  options?: MoveOptions<S>,
  out?: Move<S>,
): Move<S> {
  const result = (out ?? shared) as Move<S>;
  result.dx = 0;
  result.dy = 0;
  result.left = false;
  result.right = false;
  result.top = false;
  result.bottom = false;
  result.hitX = null;
  result.hitY = null;
  body = mover;
  drop = options?.dropThrough ?? false;
  filter = options?.filter as ((solid: Solid) => boolean) | undefined;
  try {
    if (Number.isFinite(dx) && dx !== 0) {
      allowed = dx;
      forward = dx > 0;
      hit = null;
      area.x = Math.min(mover.x, mover.x + dx);
      area.y = mover.y;
      area.w = mover.w + Math.abs(dx);
      area.h = mover.h;
      sweep(solids, visitX);
      mover.x += allowed;
      result.dx = allowed;
      if (hit) {
        result.hitX = hit as S;
        if (dx > 0) result.right = true;
        else result.left = true;
      }
    }
    if (Number.isFinite(dy) && dy !== 0) {
      allowed = dy;
      forward = dy > 0;
      hit = null;
      area.x = mover.x;
      area.y = Math.min(mover.y, mover.y + dy);
      area.w = mover.w;
      area.h = mover.h + Math.abs(dy);
      sweep(solids, visitY);
      mover.y += allowed;
      result.dy = allowed;
      if (hit) {
        result.hitY = hit as S;
        if (dy > 0) result.bottom = true;
        else result.top = true;
      }
    }
  } finally {
    body = area;
    hit = null;
    filter = undefined;
  }
  return result;
}
