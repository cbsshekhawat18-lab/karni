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

/** Where the centre must go on one axis so the target is inside the dead zone. */
function goal(current: number, target: number, zone: number): number {
  const half = zone / 2;
  if (target > current + half) return target - half;
  if (target < current - half) return target + half;
  return current;
}

/**
 * The camera is a class with every number field started as a number: `x`
 * and `y` change every frame, and V8 writes a number field in place only
 * when the field never held anything else (a field declared bare starts as
 * undefined, and a literal with getters keeps no number fields).
 */
class Camera2D implements Camera {
  x = 0;
  y = 0;
  zoom = 1;
  bounds: Area | null = null;
  readonly deadZone: { w: number; h: number };
  readonly offset: { x: number; y: number };
  smoothing = 0;
  motion = 1;
  private target: FollowTarget | null = null;
  private strength = 0;
  private duration = 0;
  private remaining = 0;
  private sx = 0;
  private sy = 0;

  constructor(
    private readonly view: { readonly width: number; readonly height: number },
    private readonly random: () => number,
    options: CameraOptions,
  ) {
    this.x = options.x ?? view.width / 2;
    this.y = options.y ?? view.height / 2;
    this.zoom = options.zoom ?? 1;
    this.bounds = options.bounds ?? null;
    this.deadZone = { w: options.deadZone?.w ?? 0, h: options.deadZone?.h ?? 0 };
    this.offset = { x: options.offset?.x ?? 0, y: options.offset?.y ?? 0 };
    this.smoothing = options.smoothing ?? 0;
    this.motion = options.motion ?? motionScale();
  }

  private safeZoom(): number {
    return this.zoom > 0 && Number.isFinite(this.zoom) ? this.zoom : 1;
  }

  private clamp(): void {
    const bounds = this.bounds;
    if (!bounds) return;
    const zoom = this.safeZoom();
    this.x = clampAxis(this.x, bounds.x, bounds.w, this.view.width / zoom / 2);
    this.y = clampAxis(this.y, bounds.y, bounds.h, this.view.height / zoom / 2);
  }

  follow(next: FollowTarget | null): void {
    this.target = next;
  }

  snap(): void {
    const target = this.target;
    if (target) {
      this.x = target.x + (target.w ?? 0) / 2 - this.offset.x;
      this.y = target.y + (target.h ?? 0) / 2 - this.offset.y;
    }
    this.clamp();
  }

  update(dt: number): void {
    const step = Number.isFinite(dt) && dt > 0 ? dt : 0;
    const target = this.target;
    if (target) {
      const gx = goal(this.x, target.x + (target.w ?? 0) / 2 - this.offset.x, this.deadZone.w);
      const gy = goal(this.y, target.y + (target.h ?? 0) / 2 - this.offset.y, this.deadZone.h);
      if (this.smoothing > 0) {
        const k = step > 0 ? 1 - Math.exp(-this.smoothing * step) : 0;
        this.x += (gx - this.x) * k;
        this.y += (gy - this.y) * k;
      } else {
        this.x = gx;
        this.y = gy;
      }
    }
    this.clamp();
    // A frame with no time (paused) holds the shake where it is.
    if (step > 0) {
      if (this.remaining > 0) this.remaining = Math.max(0, this.remaining - step);
      const fade = this.remaining > 0 ? this.remaining / this.duration : 0;
      const amount = this.strength * fade * fade * Math.max(0, Math.min(1, this.motion));
      if (amount > 0) {
        this.sx = (this.random() * 2 - 1) * amount;
        this.sy = (this.random() * 2 - 1) * amount;
      } else {
        this.sx = 0;
        this.sy = 0;
      }
    }
  }

  shake(strength: number, seconds = 0.25): void {
    if (!(strength > 0) || !(seconds > 0)) return;
    const current = this.remaining > 0 ? this.strength * (this.remaining / this.duration) ** 2 : 0;
    if (strength < current) return;
    this.strength = strength;
    this.duration = seconds;
    this.remaining = seconds;
  }

  get shakeX(): number {
    return this.sx;
  }
  get shakeY(): number {
    return this.sy;
  }
  get left(): number {
    return this.x - this.view.width / this.safeZoom() / 2;
  }
  get top(): number {
    return this.y - this.view.height / this.safeZoom() / 2;
  }
  get width(): number {
    return this.view.width / this.safeZoom();
  }
  get height(): number {
    return this.view.height / this.safeZoom();
  }

  sees(x: number, y: number, w: number, h: number): boolean {
    const zoom = this.safeZoom();
    const hw = this.view.width / zoom / 2;
    const hh = this.view.height / zoom / 2;
    return x + w >= this.x - hw && x <= this.x + hw && y + h >= this.y - hh && y <= this.y + hh;
  }

  toScreen(x: number, y: number, out: Point): Point {
    const zoom = this.safeZoom();
    out.x = (x - this.x - this.sx) * zoom + this.view.width / 2;
    out.y = (y - this.y - this.sy) * zoom + this.view.height / 2;
    return out;
  }

  toWorld(x: number, y: number, out: Point): Point {
    const zoom = this.safeZoom();
    out.x = (x - this.view.width / 2) / zoom + this.x + this.sx;
    out.y = (y - this.view.height / 2) / zoom + this.y + this.sy;
    return out;
  }
}

/**
 * A 2D camera over a view: it follows a target with a dead zone and
 * smoothing, stays inside the world's bounds, shakes and zooms. The renderer
 * applies it to every layer that is not a screen layer.
 */
export function createCamera(options: CameraOptions): Camera {
  return new Camera2D(options.view, options.random ?? generator(1), options);
}
