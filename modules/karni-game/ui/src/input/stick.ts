import type { Input, PointerState } from "./input";

export interface VirtualStickOptions {
  /**
   * Where a finger must go down to grab the stick, in the input's units.
   * Default: the left half of `area`.
   */
  zone?: (x: number, y: number) => boolean;
  /** The game area, for the default zone. Default the window's size. */
  area?: () => { width: number; height: number };
  /** How far the knob travels from where the finger went down. Default 60. */
  radius?: number;
  /** Deflection below this (0 to 1) reads as centred. Default 0.15. */
  deadZone?: number;
  /** Deflection past this presses the direction codes. Default 0.5. */
  threshold?: number;
  /** Only touches grab the stick (a mouse keeps its clicks). Default true. */
  touchOnly?: boolean;
}

/** Codes the stick presses on the input, for bindings: `left: ["ArrowLeft", STICK.left]`. */
export const STICK = {
  left: "StickLeft",
  right: "StickRight",
  up: "StickUp",
  down: "StickDown",
} as const;

export interface VirtualStick {
  /** Deflection from -1 to 1 on each axis, 0 inside the dead zone. */
  readonly x: number;
  readonly y: number;
  /** A finger is on the stick. */
  readonly active: boolean;
  /** Where the finger went down and where the knob is, for drawing. */
  readonly origin: { x: number; y: number } | null;
  readonly knob: { x: number; y: number } | null;
  readonly radius: number;
  /** Draw a plain stick (ring and knob). Games with their own art read `origin` and `knob`. */
  draw(context: CanvasRenderingContext2D, style?: { ring?: string; knob?: string }): void;
  destroy(): void;
}

/**
 * A floating touch stick: it appears under the thumb that lands in its zone,
 * reports a deflection, and presses the STICK codes so the same bindings
 * serve the keyboard and the touch screen. The finger it owns does not count
 * as the "Pointer" key.
 */
export function createVirtualStick(input: Input, options: VirtualStickOptions = {}): VirtualStick {
  const radius = options.radius ?? 60;
  const deadZone = options.deadZone ?? 0.15;
  const threshold = options.threshold ?? 0.5;
  const touchOnly = options.touchOnly ?? true;
  const area = options.area ?? (() => ({ width: window.innerWidth, height: window.innerHeight }));
  const zone = options.zone ?? ((x: number) => x < area().width / 2);

  let owner: number | null = null;
  let origin: { x: number; y: number } | null = null;
  let knob: { x: number; y: number } | null = null;
  let x = 0;
  let y = 0;

  const setCode = (code: string, on: boolean): void => {
    if (on) input.press(code);
    else input.release(code);
  };
  const update = (pointer: PointerState): void => {
    if (!origin) return;
    let dx = (pointer.x - origin.x) / radius;
    let dy = (pointer.y - origin.y) / radius;
    const length = Math.hypot(dx, dy);
    if (length > 1) {
      dx /= length;
      dy /= length;
    }
    knob = { x: origin.x + dx * radius, y: origin.y + dy * radius };
    const live = Math.hypot(dx, dy) >= deadZone;
    x = live ? dx : 0;
    y = live ? dy : 0;
    setCode(STICK.left, x <= -threshold);
    setCode(STICK.right, x >= threshold);
    setCode(STICK.up, y <= -threshold);
    setCode(STICK.down, y >= threshold);
  };
  const reset = (): void => {
    owner = null;
    origin = null;
    knob = null;
    x = 0;
    y = 0;
    for (const code of Object.values(STICK)) input.release(code);
  };

  const off = [
    input.onPointerDown((pointer) => {
      if (owner !== null) return false;
      if (touchOnly && pointer.type !== "touch") return false;
      if (!zone(pointer.x, pointer.y)) return false;
      owner = pointer.id;
      origin = { x: pointer.x, y: pointer.y };
      knob = { ...origin };
      return true;
    }),
    input.onPointerMove((pointer) => {
      if (pointer.id === owner) update(pointer);
    }),
    input.onPointerUp((pointer) => {
      if (pointer.id === owner) reset();
    }),
  ];

  return {
    get x() {
      return x;
    },
    get y() {
      return y;
    },
    get active() {
      return owner !== null;
    },
    get origin() {
      return origin;
    },
    get knob() {
      return knob;
    },
    radius,
    draw(context, style = {}) {
      if (!origin || !knob) return;
      context.save();
      context.globalAlpha = 0.5;
      context.strokeStyle = style.ring ?? "#ffffff";
      context.lineWidth = 3;
      context.beginPath();
      context.arc(origin.x, origin.y, radius, 0, Math.PI * 2);
      context.stroke();
      context.fillStyle = style.knob ?? "#ffffff";
      context.beginPath();
      context.arc(knob.x, knob.y, radius * 0.4, 0, Math.PI * 2);
      context.fill();
      context.restore();
    },
    destroy() {
      for (const unsubscribe of off) unsubscribe();
      reset();
    },
  };
}
