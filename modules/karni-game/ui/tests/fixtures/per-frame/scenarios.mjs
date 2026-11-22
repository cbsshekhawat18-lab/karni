/**
 * Per-frame allocation of the draw and collide bundles, run by
 * tests/draw-collide-bundle.test.ts in a Node process of its own with
 * --expose-gc: `node --expose-gc scenarios.mjs <dir with draw.js and collide.js>`.
 * Prints one JSON object: bytes the heap grew per frame, per scenario.
 */
import { pathToFileURL } from "node:url";
import { join } from "node:path";

const dir = process.argv[2];
const D = await import(pathToFileURL(join(dir, "draw.js")).href);
const C = await import(pathToFileURL(join(dir, "collide.js")).href);
const gc = globalThis.gc;

/** Best of three rounds, each scenario on a loop of its own so no call site is shared. */
function perFrame(frame, times = 20000) {
  const run = new Function("frame", "n", "for (let i = 0; i < n; i += 1) frame();");
  run(frame, 5000);
  let best = Infinity;
  for (let round = 0; round < 3; round += 1) {
    gc();
    const before = process.memoryUsage().heapUsed;
    run(frame, times);
    best = Math.min(best, (process.memoryUsage().heapUsed - before) / times);
  }
  return best;
}

/** A 2D context that does nothing and builds nothing. */
class Silent {
  canvas = { width: 960, height: 540 };
  fillStyle = "#000000";
  strokeStyle = "#000000";
  globalAlpha = 1;
  globalCompositeOperation = "source-over";
  font = "10px sans-serif";
  textAlign = "start";
  textBaseline = "alphabetic";
  lineWidth = 1;
  lineJoin = "miter";
  imageSmoothingEnabled = true;
  metrics = { width: 0 };
  save() {}
  restore() {}
  setTransform() {}
  transform() {}
  fillRect() {}
  strokeRect() {}
  clearRect() {}
  beginPath() {}
  closePath() {}
  rect() {}
  clip() {}
  arc() {}
  moveTo() {}
  lineTo() {}
  fill() {}
  stroke() {}
  fillText() {}
  strokeText() {}
  measureText(text) {
    this.metrics.width = text.length * 6;
    return this.metrics;
  }
  drawImage() {}
}

const view = { width: 480, height: 270, dpr: 1, scale: 2, offsetX: 0, offsetY: 0 };
const results = {};

{
  // A frame of the renderer: a camera that follows and shakes, 50 rects, shapes, text, sprites.
  const camera = D.createCamera({ view, motion: 1, smoothing: 6, deadZone: { w: 40, h: 30 } });
  const target = { x: 0.5, y: 100, w: 16, h: 16 };
  camera.follow(target);
  const renderer = D.createRenderer({
    context: new Silent(),
    view,
    camera,
    layers: [{ name: "far", parallax: 0.4 }, "world", { name: "hud", screen: true }],
  });
  const frames = D.sheetFrames({ width: 64, height: 16 }, 16, 16, { anchor: [0.5, 0.5] });
  const animator = D.createAnimator(
    D.defineClips(frames, { run: { frames: { from: 0, to: 3 }, fps: 12 } }),
    "run",
  );
  const label = D.textStyle({ font: "12px sans-serif", wrap: 120 });
  const hud = D.textStyle({ font: "14px sans-serif", stroke: "#000" });
  const points = [0, 0, 20, 0, 10, 15];
  renderer.on("far", (g) => g.rect(0, 0, 2000, 100, "#123"));
  renderer.on("world", (g) => {
    for (let i = 0; i < 50; i += 1) g.rect(i * 40, 180, 30, 8, "#789");
    g.circle(target.x, target.y, 6, "#fd6");
    g.poly(points, "#f00", "#fff", 1);
    g.sprite(animator.sprite, target.x, target.y);
    g.sprite(animator.sprite, target.x, target.y, -1, 1, 0.3);
    g.text("a sign with words that wrap", 300, 120, label);
  });
  renderer.on("hud", (g) => g.text("Score", 8, 8, hud));
  const clock = { frame: 0 };
  results.render = perFrame(() => {
    clock.frame += 1;
    target.x = (target.x + 2.5) % 2000;
    if (clock.frame % 120 === 0) camera.shake(4, 0.2);
    camera.update(1 / 60);
    animator.update(1 / 60);
    renderer.render(0.5, 1 / 60);
  });
}

{
  // 300 particles at the cap: bursts, a stream, ageing with gravity and drag, drawn.
  const renderer = D.createRenderer({ context: new Silent(), view, layers: ["fx"] });
  const seed = { n: 1 };
  const random = () => {
    seed.n = (seed.n * 16807) % 2147483647;
    return seed.n / 2147483647;
  };
  const particles = D.createParticles({ max: 300, random, motion: 1 });
  const sparks = particles.emitter({ speed: [50, 150], life: [0.2, 0.5], gravity: 300, drag: 1 });
  const glow = particles.emitter({ shape: "circle", blend: "lighter", colors: ["#fd6", "#f96"] });
  renderer.on("fx", (g) => particles.draw(g));
  const clock = { frame: 0 };
  results.particles = perFrame(() => {
    clock.frame += 1;
    if (clock.frame % 10 === 0) sparks.burst(240, 135, 40);
    glow.flow(100, 100, 120, 1 / 60);
    particles.update(1 / 60);
    renderer.render(0, 1 / 60);
  });
  results.particlesAlive = particles.count;
}

{
  // 50 tweens running for ever, and a pool of 200 spawning and retiring.
  const tweens = D.createTweens();
  for (let i = 0; i < 50; i += 1) {
    const thing = { x: i + 0.5, alpha: 1 };
    tweens.to(thing, { x: thing.x + 100, alpha: 0 }, 2, {
      ease: D.outQuad,
      repeat: Infinity,
      yoyo: true,
    });
  }
  const pool = D.createPool({ create: () => ({ life: 0 }), max: 200, prefill: 200 });
  const age = (item) => (item.life -= 1) > 0;
  results.tweens = perFrame(() => {
    const item = pool.acquire();
    if (item) item.life = 30;
    pool.retain(age);
    tweens.update(1 / 60);
  });
}

{
  // A body moving on a level of 100 solids (some one-way), a sweep, 40 trigger zones.
  const solids = [];
  for (let i = 0; i < 100; i += 1) {
    solids.push({ x: i * 50, y: 200 + (i % 3) * 10, w: 40, h: 10, oneWay: i % 4 === 0 });
  }
  const body = { x: 10.5, y: 0.5, w: 14, h: 18 };
  const move = C.createMove();
  const hit = C.createHit();
  const state = { vy: 0.5, dir: 1, entered: 0 };
  const triggers = C.createTriggers({ enter: () => (state.entered += 1) });
  for (let i = 0; i < 40; i += 1) triggers.add({ x: i * 120, y: 150, w: 10, h: 60 });
  results.collide = perFrame(() => {
    state.vy += 0.1;
    C.moveBox(body, state.dir * 2, state.vy, solids, undefined, move);
    if (move.bottom) state.vy = -4;
    if (body.x > 4800 || body.x < 0) state.dir = -state.dir;
    C.sweepBox(body, state.dir * 10, state.vy, solids[3], hit);
    triggers.update(body);
  });
  results.triggersEntered = state.entered;
}

process.stdout.write(JSON.stringify(results));
