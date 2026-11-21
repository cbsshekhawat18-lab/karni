import { motionScale } from "./motion";
import type { Point } from "./types";

/** An area of the world: `x`, `y` is its top-left corner. */
export interface Area {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** What a camera follows: a point, or a box (its centre is followed). */
export interface FollowTarget {
  readonly x: number;
  readonly y: number;
  readonly w?: number;
  readonly h?: number;
}

export interface CameraOptions {
  /** The size the camera shows at zoom 1, in game units: the view (`createView`). */
  view: { readonly width: number; readonly height: number };
  /** The world point at the centre of the screen. Default the view's centre. */
  x?: number;
  y?: number;
  /** Default 1. Above 1 shows less of the world, larger. */
  zoom?: number;
  /** The camera never shows outside this area. A world smaller than the screen is centred. */
  bounds?: Area | null;
  /** The target moves this far from the centre (a box, in game units) before the camera moves. */
  deadZone?: { w: number; h: number };
  /** Where the target sits from the centre of the screen: `{ x: -80 }` shows more ahead of a runner. */
  offset?: { x: number; y: number };
  /** How fast the camera catches up, per second (8 is quick, 2 is lazy). 0 snaps. Default 0. */
  smoothing?: number;
  /** The share of shake kept, 0 to 1. Default 1, or 0.25 when the browser asks for less motion. */
  motion?: number;
  /** The random source of the shake. Default a small generator of its own. */
  random?: () => number;
}

export interface Camera {
  /** The world point at the centre of the screen, before shake. */
  x: number;
  y: number;
  zoom: number;
  bounds: Area | null;
  readonly deadZone: { w: number; h: number };
  readonly offset: { x: number; y: number };
  smoothing: number;
  /** The share of shake kept, 0 to 1: set it from the game's reduced-motion setting. */
  motion: number;
  /** Follow a point or a box, or stop following (null). */
  follow(target: FollowTarget | null): void;
  /** Move to the target at once, with no smoothing: on a level start or a respawn. */
  snap(): void;
  /** Follow, smooth, shake and keep in bounds. Call once a frame with the real frame time. */
  update(dt: number): void;
  /** Shake by `strength` game units, fading over `seconds`. A weaker shake does not cut a stronger one. */
  shake(strength: number, seconds?: number): void;
  /** The shake of this frame, in world units. */
  readonly shakeX: number;
  readonly shakeY: number;
  /** The world area on screen (zoom included, shake not). */
  readonly left: number;
  readonly top: number;
  readonly width: number;
  readonly height: number;
  /** True when a box of the world is at least partly on screen. */
  sees(x: number, y: number, w: number, h: number): boolean;
  /** A world point to game units on screen, written into `out`. */
  toScreen(x: number, y: number, out: Point): Point;
  /** A point on screen, in game units (`view.toGame`), to the world, written into `out`. */
  toWorld(x: number, y: number, out: Point): Point;
}

/** mulberry32: shake needs noise, not a seeded stream, but a test needs it repeatable. */
function generator(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function clampAxis(value: number, start: number, size: number, half: number): number {
  if (!(size > half * 2)) return start + size / 2;
  const low = start + half;
  const high = start + size - half;
  if (value < low) return low;
  if (value > high) return high;
  return value;
}

/**
 * A 2D camera over a view: it follows a target with a dead zone and
 * smoothing, stays inside the world's bounds, shakes and zooms. The renderer
 * applies it to every layer that is not a screen layer.
 */
export function createCamera(options: CameraOptions): Camera {
  const view = options.view;
  const random = options.random ?? generator(1);
  let target: FollowTarget | null = null;
  let shakeStrength = 0;
  let shakeTime = 0;
  let shakeLeft = 0;
  let shakeX = 0;
  let shakeY = 0;

  const safeZoom = (): number =>
    camera.zoom > 0 && Number.isFinite(camera.zoom) ? camera.zoom : 1;

  const clamp = (): void => {
    const bounds = camera.bounds;
    if (!bounds) return;
    const zoom = safeZoom();
    const hw = view.width / zoom / 2;
    const hh = view.height / zoom / 2;
    camera.x = clampAxis(camera.x, bounds.x, bounds.w, hw);
    camera.y = clampAxis(camera.y, bounds.y, bounds.h, hh);
  };

  /** Where the centre must go so the target is inside the dead zone. */
  const goalX = (): number => {
    if (!target) return camera.x;
    const tx = target.x + (target.w ?? 0) / 2 - camera.offset.x;
    const dz = camera.deadZone.w / 2;
    if (tx > camera.x + dz) return tx - dz;
    if (tx < camera.x - dz) return tx + dz;
    return camera.x;
  };
  const goalY = (): number => {
    if (!target) return camera.y;
    const ty = target.y + (target.h ?? 0) / 2 - camera.offset.y;
    const dz = camera.deadZone.h / 2;
    if (ty > camera.y + dz) return ty - dz;
    if (ty < camera.y - dz) return ty + dz;
    return camera.y;
  };

  const camera: Camera = {
    x: options.x ?? view.width / 2,
    y: options.y ?? view.height / 2,
    zoom: options.zoom ?? 1,
    bounds: options.bounds ?? null,
    deadZone: { w: options.deadZone?.w ?? 0, h: options.deadZone?.h ?? 0 },
    offset: { x: options.offset?.x ?? 0, y: options.offset?.y ?? 0 },
    smoothing: options.smoothing ?? 0,
    motion: options.motion ?? motionScale(),
    follow(next) {
      target = next;
    },
    snap() {
      if (target) {
        camera.x = target.x + (target.w ?? 0) / 2 - camera.offset.x;
        camera.y = target.y + (target.h ?? 0) / 2 - camera.offset.y;
      }
      clamp();
    },
    update(dt) {
      const step = Number.isFinite(dt) && dt > 0 ? dt : 0;
      const gx = goalX();
      const gy = goalY();
      if (camera.smoothing > 0 && step > 0) {
        const k = 1 - Math.exp(-camera.smoothing * step);
        camera.x += (gx - camera.x) * k;
        camera.y += (gy - camera.y) * k;
      } else if (camera.smoothing <= 0) {
        camera.x = gx;
        camera.y = gy;
      }
      clamp();
      if (shakeLeft > 0 && step > 0) {
        shakeLeft = Math.max(0, shakeLeft - step);
        const fade = shakeLeft / shakeTime;
        const amount = shakeStrength * fade * fade * Math.max(0, Math.min(1, camera.motion));
        shakeX = (random() * 2 - 1) * amount;
        shakeY = (random() * 2 - 1) * amount;
      } else if (shakeLeft <= 0) {
        shakeX = 0;
        shakeY = 0;
      }
    },
    shake(strength, seconds = 0.25) {
      if (!(strength > 0) || !(seconds > 0)) return;
      const current = shakeLeft > 0 ? shakeStrength * (shakeLeft / shakeTime) ** 2 : 0;
      if (strength < current) return;
      shakeStrength = strength;
      shakeTime = seconds;
      shakeLeft = seconds;
    },
    get shakeX() {
      return shakeX;
    },
    get shakeY() {
      return shakeY;
    },
    get left() {
      return camera.x - view.width / safeZoom() / 2;
    },
    get top() {
      return camera.y - view.height / safeZoom() / 2;
    },
    get width() {
      return view.width / safeZoom();
    },
    get height() {
      return view.height / safeZoom();
    },
    sees(x, y, w, h) {
      const zoom = safeZoom();
      const hw = view.width / zoom / 2;
      const hh = view.height / zoom / 2;
      return (
        x + w >= camera.x - hw && x <= camera.x + hw && y + h >= camera.y - hh && y <= camera.y + hh
      );
    },
    toScreen(x, y, out) {
      const zoom = safeZoom();
      out.x = (x - camera.x - shakeX) * zoom + view.width / 2;
      out.y = (y - camera.y - shakeY) * zoom + view.height / 2;
      return out;
    },
    toWorld(x, y, out) {
      const zoom = safeZoom();
      out.x = (x - view.width / 2) / zoom + camera.x + shakeX;
      out.y = (y - view.height / 2) / zoom + camera.y + shakeY;
      return out;
    },
  };
  return camera;
}
