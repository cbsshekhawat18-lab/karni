import type { Box, Circle } from "./shapes";

/** Where a moving point or shape first touches another. */
export interface Hit {
  /** The share of the move made before the touch, 0 to 1. */
  time: number;
  /** The moving point (or the moving shape's x, y) at the touch. */
  x: number;
  y: number;
  /** The surface's normal at the touch, a unit vector. 0, 0 when the move started inside. */
  nx: number;
  ny: number;
}

export function createHit(): Hit {
  return { time: 0, x: 0, y: 0, nx: 0, ny: 0 };
}

/** The slab test of a segment against an area: the core of every box sweep. */
function slab(
  x: number,
  y: number,
  dx: number,
  dy: number,
  minX: number,
  minY: number,
  maxX: number,
  maxY: number,
  out: Hit | undefined,
): boolean {
  let near = -Infinity;
  let far = Infinity;
  let nx = 0;
  let ny = 0;
  if (dx === 0) {
    // Moving along an edge, or beside the box, is no touch.
    if (x <= minX || x >= maxX) return false;
  } else {
    let t1 = (minX - x) / dx;
    let t2 = (maxX - x) / dx;
    let n = -1;
    if (t1 > t2) {
      const t = t1;
      t1 = t2;
      t2 = t;
      n = 1;
    }
    if (t1 > near) {
      near = t1;
      nx = n;
      ny = 0;
    }
    if (t2 < far) far = t2;
  }
  if (dy === 0) {
    if (y <= minY || y >= maxY) return false;
  } else {
    let t1 = (minY - y) / dy;
    let t2 = (maxY - y) / dy;
    let n = -1;
    if (t1 > t2) {
      const t = t1;
      t1 = t2;
      t2 = t;
      n = 1;
    }
    if (t1 > near) {
      near = t1;
      nx = 0;
      ny = n;
    }
    if (t2 < far) far = t2;
  }
  // Grazing a corner, moving away from a touching side, or passing short of it: no hit.
  if (near >= far || far <= 0 || near > 1) return false;
  if (out) {
    const time = near < 0 ? 0 : near;
    out.time = time;
    out.x = x + dx * time;
    out.y = y + dy * time;
    out.nx = near < 0 ? 0 : nx;
    out.ny = near < 0 ? 0 : ny;
  }
  return true;
}

/** A segment from x, y along dx, dy against a box (a ray cast, a bullet's path). */
export function segmentBox(
  x: number,
  y: number,
  dx: number,
  dy: number,
  box: Box,
  out?: Hit,
): boolean {
  return slab(x, y, dx, dy, box.x, box.y, box.x + box.w, box.y + box.h, out);
}

/** The segment test against a circle at cx, cy of radius r. */
function circleRay(
  x: number,
  y: number,
  dx: number,
  dy: number,
  cx: number,
  cy: number,
  r: number,
  out: Hit | undefined,
): boolean {
  const ox = x - cx;
  const oy = y - cy;
  const c = ox * ox + oy * oy - r * r;
  if (c < 0) {
    if (out) {
      out.time = 0;
      out.x = x;
      out.y = y;
      out.nx = 0;
      out.ny = 0;
    }
    return true;
  }
  const a = dx * dx + dy * dy;
  if (a === 0) return false;
  const b = 2 * (ox * dx + oy * dy);
  const disc = b * b - 4 * a * c;
  if (disc < 0) return false;
  const t = (-b - Math.sqrt(disc)) / (2 * a);
  if (t < 0 || t > 1) return false;
  if (out) {
    out.time = t;
    out.x = x + dx * t;
    out.y = y + dy * t;
    out.nx = (out.x - cx) / r;
    out.ny = (out.y - cy) / r;
  }
  return true;
}

/** A segment from x, y along dx, dy against a circle. */
export function segmentCircle(
  x: number,
  y: number,
  dx: number,
  dy: number,
  circle: Circle,
  out?: Hit,
): boolean {
  return circleRay(x, y, dx, dy, circle.x, circle.y, circle.r, out);
}

/**
 * Box `a` moving by dx, dy against box `b` that stands still: the first
 * touch, so a fast box never passes through a thin one. `out.x`, `out.y` is
 * where `a` stops.
 */
export function sweepBox(a: Box, dx: number, dy: number, b: Box, out?: Hit): boolean {
  return slab(a.x, a.y, dx, dy, b.x - a.w, b.y - a.h, b.x + b.w, b.y + b.h, out);
}

/** Circle `a` moving by dx, dy against circle `b` that stands still. `out.x`, `out.y` is `a`'s centre. */
export function sweepCircle(a: Circle, dx: number, dy: number, b: Circle, out?: Hit): boolean {
  // Grow b by a's radius and cast a's centre: the normal of the grown circle is the one between them.
  return circleRay(a.x, a.y, dx, dy, b.x, b.y, a.r + b.r, out);
}

/**
 * The nearest of `boxes` a segment from x, y along dx, dy touches, or null:
 * line of sight, a laser, where a shot lands. `out` gets the touch.
 */
export function castRay<T extends Box>(
  x: number,
  y: number,
  dx: number,
  dy: number,
  boxes: readonly T[],
  out: Hit,
  filter?: (box: T) => boolean,
): T | null {
  let best: T | null = null;
  let time = Infinity;
  let bx = 0;
  let by = 0;
  let bnx = 0;
  let bny = 0;
  for (let i = 0; i < boxes.length; i += 1) {
    const box = boxes[i] as T;
    if (filter && !filter(box)) continue;
    if (segmentBox(x, y, dx, dy, box, out) && out.time < time) {
      best = box;
      time = out.time;
      bx = out.x;
      by = out.y;
      bnx = out.nx;
      bny = out.ny;
    }
  }
  if (best) {
    out.time = time;
    out.x = bx;
    out.y = by;
    out.nx = bnx;
    out.ny = bny;
  }
  return best;
}
