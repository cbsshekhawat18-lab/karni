/**
 * An axis-aligned box: `x`, `y` is its top-left corner. Any object with these
 * four numbers is one, so an entity can be passed as itself.
 */
export interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** A circle: `x`, `y` is its centre. */
export interface Circle {
  x: number;
  y: number;
  r: number;
}

/** How to push one shape out of another: along the normal, by the depth. */
export interface Contact {
  /** The direction to move the first shape, a unit vector. */
  nx: number;
  ny: number;
  /** How far, in world units. */
  depth: number;
}

export function createContact(): Contact {
  return { nx: 0, ny: 0, depth: 0 };
}

/** Touching edges do not overlap: a box standing on a floor is not inside it. */
export function boxesOverlap(a: Box, b: Box): boolean {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
}

export function circlesOverlap(a: Circle, b: Circle): boolean {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  const r = a.r + b.r;
  return dx * dx + dy * dy < r * r;
}

export function boxCircleOverlap(box: Box, circle: Circle): boolean {
  const cx = Math.max(box.x, Math.min(circle.x, box.x + box.w));
  const cy = Math.max(box.y, Math.min(circle.y, box.y + box.h));
  const dx = circle.x - cx;
  const dy = circle.y - cy;
  return dx * dx + dy * dy < circle.r * circle.r;
}

export function pointInBox(x: number, y: number, box: Box): boolean {
  return x >= box.x && x < box.x + box.w && y >= box.y && y < box.y + box.h;
}

export function pointInCircle(x: number, y: number, circle: Circle): boolean {
  const dx = x - circle.x;
  const dy = y - circle.y;
  return dx * dx + dy * dy < circle.r * circle.r;
}

/** True when `a` overlaps `b`, with the shortest push of `a` out of it in `out`. */
export function boxContact(a: Box, b: Box, out: Contact): boolean {
  const left = a.x + a.w - b.x;
  const right = b.x + b.w - a.x;
  const up = a.y + a.h - b.y;
  const down = b.y + b.h - a.y;
  if (left <= 0 || right <= 0 || up <= 0 || down <= 0) return false;
  const x = Math.min(left, right);
  const y = Math.min(up, down);
  if (x < y) {
    out.nx = left < right ? -1 : 1;
    out.ny = 0;
    out.depth = x;
  } else {
    out.nx = 0;
    out.ny = up < down ? -1 : 1;
    out.depth = y;
  }
  return true;
}

/** True when `a` overlaps `b`, with the push of `a` out of it in `out`. */
export function circleContact(a: Circle, b: Circle, out: Contact): boolean {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  const r = a.r + b.r;
  const d2 = dx * dx + dy * dy;
  if (d2 >= r * r) return false;
  const d = Math.sqrt(d2);
  if (d > 0) {
    out.nx = dx / d;
    out.ny = dy / d;
  } else {
    // The same centre: push up, a choice that is at least stable.
    out.nx = 0;
    out.ny = -1;
  }
  out.depth = r - d;
  return true;
}

/** True when the circle overlaps the box, with the push of the circle out of it in `out`. */
export function circleBoxContact(circle: Circle, box: Box, out: Contact): boolean {
  const cx = Math.max(box.x, Math.min(circle.x, box.x + box.w));
  const cy = Math.max(box.y, Math.min(circle.y, box.y + box.h));
  const dx = circle.x - cx;
  const dy = circle.y - cy;
  const d2 = dx * dx + dy * dy;
  if (d2 >= circle.r * circle.r) return false;
  if (d2 > 0) {
    const d = Math.sqrt(d2);
    out.nx = dx / d;
    out.ny = dy / d;
    out.depth = circle.r - d;
    return true;
  }
  // The centre is inside the box: out through the nearest side.
  const left = circle.x - box.x;
  const right = box.x + box.w - circle.x;
  const up = circle.y - box.y;
  const down = box.y + box.h - circle.y;
  const least = Math.min(left, right, up, down);
  out.nx = least === left ? -1 : least === right ? 1 : 0;
  out.ny = out.nx !== 0 ? 0 : least === up ? -1 : 1;
  out.depth = least + circle.r;
  return true;
}
