import { motionScale } from "./motion";
import type { Painter } from "./painter";
import { createPool, type Pool } from "./pool";
import type { Sprite } from "./sprite";
import type { Paint } from "./types";

/** A number, or a range a value is picked from for each particle. */
export type Range = number | readonly [number, number];

export interface ParticleStyle {
  /** Units per second. Default [40, 120]. */
  speed?: Range;
  /** Direction in radians (0 is right, Math.PI / 2 is down). Default all round. */
  angle?: Range;
  /** Seconds. Default [0.4, 0.8]. */
  life?: Range;
  /** Width in units. Default 3. */
  size?: Range;
  /** Size at the end of life as a share of the start: 0 shrinks away. Default 0. */
  endSize?: number;
  /** Picked from for each particle. Default white. */
  colors?: readonly Paint[];
  /** Units per second squared, down. Default 0. */
  gravity?: number;
  /** Share of speed lost per second. Default 0. */
  drag?: number;
  /** Fade out over life. Default true. */
  fade?: boolean;
  /** Default "square" (the cheapest to draw). */
  shape?: "square" | "circle" | Sprite;
  /** Particles start anywhere within this distance of the point. Default 0. */
  spread?: number;
  /** How particles mix with what is under them: "lighter" adds light. Default normal. */
  blend?: GlobalCompositeOperation;
}

interface Resolved {
  speed: readonly [number, number];
  angle: readonly [number, number];
  life: readonly [number, number];
  size: readonly [number, number];
  endSize: number;
  colors: readonly Paint[];
  gravity: number;
  drag: number;
  fade: boolean;
  shape: "square" | "circle" | Sprite;
  spread: number;
  blend: GlobalCompositeOperation;
}

interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  age: number;
  life: number;
  size: number;
  color: Paint;
  style: Resolved;
}

/** One style of particle, emitted into its system. */
export interface Emitter {
  /** `count` particles at once at x, y (fewer under reduced motion, none past the cap). */
  burst(x: number, y: number, count: number): void;
  /** A steady stream: `perSecond` particles a second, for a frame of `dt` seconds. */
  flow(x: number, y: number, perSecond: number, dt: number): void;
}

export interface ParticlesOptions {
  /** The most particles alive at once. Default 500. */
  max?: number;
  /** Random source in [0, 1). Default `Math.random` (drawing is not the game's rules). */
  random?: () => number;
  /** The share of particles kept, 0 to 1. Default 1, or 0.25 when the browser asks for less motion. */
  motion?: number;
}

export interface Particles {
  /** A style of particle to emit into this system. Make it once, not per frame. */
  emitter(style: ParticleStyle): Emitter;
  update(dt: number): void;
  draw(g: Painter): void;
  clear(): void;
  /** Particles alive. */
  readonly count: number;
  readonly max: number;
  /** The share of particles kept: set it from the game's reduced-motion setting. */
  motion: number;
}

const range = (
  value: Range | undefined,
  fallback: readonly [number, number],
): readonly [number, number] =>
  value === undefined ? fallback : typeof value === "number" ? [value, value] : value;

/**
 * Pooled particles: a fixed number made up front and reused, so bursts and
 * streams make no garbage. Each emitter is one look (speed, life, size,
 * colours, gravity, shape), all drawn by `draw` in one pass.
 */
export function createParticles(options: ParticlesOptions = {}): Particles {
  const max = Math.max(1, Math.floor(options.max ?? 500));
  const random = options.random ?? Math.random;
  const blank: Resolved = {
    speed: [0, 0],
    angle: [0, 0],
    life: [1, 1],
    size: [1, 1],
    endSize: 0,
    colors: ["#ffffff"],
    gravity: 0,
    drag: 0,
    fade: true,
    shape: "square",
    spread: 0,
    blend: "source-over",
  };
  const pool: Pool<Particle> = createPool<Particle>({
    max,
    prefill: max,
    create: () => ({
      x: 0,
      y: 0,
      vx: 0,
      vy: 0,
      age: 0,
      life: 1,
      size: 1,
      color: "#ffffff",
      style: blank,
    }),
  });
  const pick = (r: readonly [number, number]): number => r[0] + (r[1] - r[0]) * random();
  let step = 0;
  const age = (p: Particle): boolean => {
    p.age += step;
    if (p.age >= p.life) return false;
    const s = p.style;
    if (s.drag > 0) {
      const keep = Math.max(0, 1 - s.drag * step);
      p.vx *= keep;
      p.vy *= keep;
    }
    p.vy += s.gravity * step;
    p.x += p.vx * step;
    p.y += p.vy * step;
    return true;
  };

  const spawn = (style: Resolved, x: number, y: number): boolean => {
    const p = pool.acquire();
    if (!p) return false;
    const angle = pick(style.angle);
    const speed = pick(style.speed);
    p.x = x;
    p.y = y;
    if (style.spread > 0) {
      const a = random() * Math.PI * 2;
      const d = Math.sqrt(random()) * style.spread;
      p.x += Math.cos(a) * d;
      p.y += Math.sin(a) * d;
    }
    p.vx = Math.cos(angle) * speed;
    p.vy = Math.sin(angle) * speed;
    p.age = 0;
    p.life = Math.max(0.001, pick(style.life));
    p.size = pick(style.size);
    p.color = style.colors[Math.floor(random() * style.colors.length)] ?? "#ffffff";
    p.style = style;
    return true;
  };

  let g: Painter | null = null;
  let lastColor: Paint | null = null;
  let lastBlend: GlobalCompositeOperation | null = null;
  const drawOne = (p: Particle): void => {
    if (!g) return;
    const s = p.style;
    const t = p.age / p.life;
    const size = p.size * (1 + (s.endSize - 1) * t);
    if (size <= 0) return;
    const half = size / 2;
    if (!g.visible(p.x - half, p.y - half, size, size)) return;
    const ctx = context as CanvasRenderingContext2D;
    if (s.blend !== lastBlend) {
      ctx.globalCompositeOperation = s.blend;
      lastBlend = s.blend;
    }
    g.alpha = s.fade ? 1 - t : 1;
    const shape = s.shape;
    if (shape === "square") {
      if (p.color !== lastColor) {
        ctx.fillStyle = p.color;
        lastColor = p.color;
      }
      ctx.fillRect(p.x - half, p.y - half, size, size);
    } else if (shape === "circle") {
      if (p.color !== lastColor) {
        ctx.fillStyle = p.color;
        lastColor = p.color;
      }
      ctx.beginPath();
      ctx.arc(p.x, p.y, half, 0, Math.PI * 2);
      ctx.fill();
    } else {
      const k = size / Math.max(shape.w, shape.h);
      g.sprite(shape, p.x, p.y, k, k);
    }
  };
  let context: CanvasRenderingContext2D | null = null;

  const particles: Particles = {
    emitter(spec) {
      const style: Resolved = {
        speed: range(spec.speed, [40, 120]),
        angle: range(spec.angle, [0, Math.PI * 2]),
        life: range(spec.life, [0.4, 0.8]),
        size: range(spec.size, [3, 3]),
        endSize: spec.endSize ?? 0,
        colors: spec.colors && spec.colors.length > 0 ? spec.colors : ["#ffffff"],
        gravity: spec.gravity ?? 0,
        drag: spec.drag ?? 0,
        fade: spec.fade ?? true,
        shape: spec.shape ?? "square",
        spread: spec.spread ?? 0,
        blend: spec.blend ?? "source-over",
      };
      let carry = 0;
      return {
        burst(x, y, count) {
          const scaled = count * Math.max(0, Math.min(1, particles.motion));
          // Under reduced motion a burst of one still shows one.
          const n = scaled > 0 && scaled < 1 ? 1 : Math.round(scaled);
          for (let i = 0; i < n; i += 1) if (!spawn(style, x, y)) return;
        },
        flow(x, y, perSecond, dt) {
          if (!(perSecond > 0) || !(dt > 0)) return;
          carry += perSecond * dt * Math.max(0, Math.min(1, particles.motion));
          while (carry >= 1) {
            carry -= 1;
            if (!spawn(style, x, y)) {
              carry = 0;
              return;
            }
          }
        },
      };
    },
    update(dt) {
      if (!(dt > 0)) return;
      step = dt;
      pool.retain(age);
    },
    draw(painter) {
      if (pool.size === 0) return;
      g = painter;
      context = painter.ctx;
      lastColor = null;
      lastBlend = null;
      pool.forEach(drawOne);
      if (lastBlend !== null && lastBlend !== "source-over")
        context.globalCompositeOperation = "source-over";
      painter.alpha = 1;
      g = null;
      context = null;
    },
    clear() {
      pool.clear();
    },
    get count() {
      return pool.size;
    },
    max,
    motion: options.motion ?? motionScale(),
  };
  return particles;
}
