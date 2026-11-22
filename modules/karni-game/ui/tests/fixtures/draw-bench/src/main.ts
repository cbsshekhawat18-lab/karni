/**
 * The 2D layer under load, for tests-browser/draw-bench.test.ts: N animated
 * sprites (some turned) across a world three screens wide, a following
 * camera, particles at their cap, running tweens, bodies on the box mover
 * and a HUD line, at the display's frame rate. It measures the time of each
 * frame's work (update and draw) and the time between frames, and leaves
 * the numbers on `window.__bench`.
 */
import { createView } from "@karni/game";
import { createMove, moveBox, type Solid } from "@karni/game/collide";
import {
  createAnimator,
  createCamera,
  createParticles,
  createRenderer,
  createTweens,
  defineClips,
  outQuad,
  sheetFrames,
  textStyle,
  type Animator,
} from "@karni/game/draw";

const params = new URLSearchParams(location.search);
const SPRITES = Number(params.get("sprites") ?? 2000);
const PARTICLES = Number(params.get("particles") ?? 1500);
const FRAMES = Number(params.get("frames") ?? 300);
const WARMUP = 60;
const W = 960;
const H = 540;
const WORLD = W * 3;

const canvas = document.getElementById("game") as HTMLCanvasElement;
const view = createView({ canvas, width: W, height: H, maxDpr: 1 });

const sheet = document.createElement("canvas");
sheet.width = 128;
sheet.height = 16;
const paint = sheet.getContext("2d") as CanvasRenderingContext2D;
for (let i = 0; i < 8; i += 1) {
  paint.fillStyle = `hsl(${i * 45}, 70%, 60%)`;
  paint.fillRect(i * 16 + 2, 2, 12, 12);
  paint.fillStyle = "#ffffff";
  paint.fillRect(i * 16 + 4 + (i % 4) * 2, 4, 3, 3);
}
const clips = defineClips(sheetFrames(sheet, 16, 16, { anchor: [0.5, 0.5] }), {
  spin: { frames: { from: 0, to: 7 }, fps: 12 },
});

interface Thing {
  x: number;
  y: number;
  vx: number;
  vy: number;
  turn: number;
  scale: number;
  animator: Animator<"spin">;
}
let seed = 7;
const random = (): number => {
  seed = (seed * 16807) % 2147483647;
  return seed / 2147483647;
};
const things: Thing[] = [];
for (let i = 0; i < SPRITES; i += 1) {
  const animator = createAnimator(clips, "spin");
  animator.update(random());
  things.push({
    x: random() * WORLD,
    y: random() * H,
    vx: (random() - 0.5) * 120,
    vy: (random() - 0.5) * 120,
    turn: i % 4 === 0 ? random() * Math.PI : 0,
    scale: 1,
    animator,
  });
}
const tweens = createTweens();
for (let i = 0; i < Math.min(200, SPRITES); i += 1) {
  tweens.to(things[i] as Thing, { scale: 2 }, 0.5 + random(), {
    ease: outQuad,
    repeat: Infinity,
    yoyo: true,
  });
}

const solids: Solid[] = [];
for (let i = 0; i < 200; i += 1) {
  solids.push({
    x: (i % 50) * 58,
    y: 120 + Math.floor(i / 50) * 120,
    w: 40,
    h: 10,
    oneWay: i % 3 === 0,
  });
}
const bodies = Array.from({ length: 50 }, (_, i) => ({
  x: i * 57 + 5,
  y: 0,
  w: 12,
  h: 16,
  vy: 0,
  dir: 1,
}));
const moved = createMove();

const camera = createCamera({
  view,
  bounds: { x: 0, y: 0, w: WORLD, h: H },
  smoothing: 5,
  motion: 1,
});
const target = { x: 0, y: H / 2 };
camera.follow(target);
const particles = createParticles({ max: PARTICLES, random, motion: 1 });
const sparks = particles.emitter({
  speed: [40, 200],
  life: [0.4, 1],
  size: [2, 4],
  gravity: 120,
  colors: ["#ffd166", "#ef476f", "#06d6a0"],
});
const hudText = textStyle({ font: "16px sans-serif", fill: "#ffffff", stroke: "#000000" });

const renderer = createRenderer({
  canvas,
  view,
  camera,
  layers: [{ name: "far", parallax: 0.4 }, "world", "effects", { name: "hud", screen: true }],
});
renderer.on("far", (g) => {
  for (let x = 0; x < WORLD; x += 120) g.rect(x, 300, 80, 240, "#1b263b");
});
renderer.on("world", (g) => {
  for (const s of solids) g.rect(s.x, s.y, s.w, s.h, s.oneWay ? "#6c757d" : "#415a77");
  for (const b of bodies) g.rect(b.x, b.y, b.w, b.h, "#ef476f");
  for (let i = 0; i < things.length; i += 1) {
    const t = things[i] as Thing;
    if (t.turn !== 0 || t.scale !== 1)
      g.sprite(t.animator.sprite, t.x, t.y, t.scale, t.scale, t.turn);
    else g.sprite(t.animator.sprite, t.x, t.y);
  }
});
renderer.on("effects", (g) => particles.draw(g));
let frame = 0;
renderer.on("hud", (g) => g.text(`frame ${frame}`, 10, 10, hudText));

const update = (dt: number): void => {
  target.x = (target.x + 300 * dt) % WORLD;
  for (let i = 0; i < things.length; i += 1) {
    const t = things[i] as Thing;
    t.x += t.vx * dt;
    t.y += t.vy * dt;
    if (t.x < 0 || t.x > WORLD) t.vx = -t.vx;
    if (t.y < 0 || t.y > H) t.vy = -t.vy;
    if (t.turn !== 0) t.turn += dt;
    t.animator.update(dt);
  }
  for (const b of bodies) {
    b.vy += 1400 * dt * dt;
    moveBox(b, b.dir * 2, b.vy, solids, undefined, moved);
    if (moved.bottom) b.vy = -6;
    if (moved.top) b.vy = 0;
    if (b.y > H) b.y = 0;
    if (b.x < 0 || b.x > WORLD) b.dir = -b.dir;
  }
  sparks.burst(camera.x + (random() - 0.5) * W, H / 2, 60);
  particles.update(dt);
  tweens.update(dt);
  camera.update(dt);
};

const work: number[] = [];
const intervals: number[] = [];
let last = 0;
let drawn = 0;
let culled = 0;

const percentile = (values: number[], p: number): number => {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * p))] ?? 0;
};

const finish = (): void => {
  const mean = (values: number[]) => values.reduce((a, b) => a + b, 0) / Math.max(1, values.length);
  (window as unknown as { __bench: unknown }).__bench = {
    sprites: SPRITES,
    particlesMax: PARTICLES,
    particles: particles.count,
    frames: work.length,
    workMean: mean(work),
    workP50: percentile(work, 0.5),
    workP95: percentile(work, 0.95),
    workMax: Math.max(...work),
    intervalMean: mean(intervals),
    intervalP95: percentile(intervals, 0.95),
    drawn,
    culled,
  };
  document.title = "done";
};

const tick = (now: number): void => {
  if (frame > WARMUP && last > 0) intervals.push(now - last);
  last = now;
  const start = performance.now();
  update(1 / 60);
  renderer.render(0, 1 / 60);
  const end = performance.now();
  frame += 1;
  if (frame > WARMUP) work.push(end - start);
  drawn = renderer.stats.drawn;
  culled = renderer.stats.culled;
  if (work.length >= FRAMES) finish();
  else requestAnimationFrame(tick);
};
requestAnimationFrame(tick);
