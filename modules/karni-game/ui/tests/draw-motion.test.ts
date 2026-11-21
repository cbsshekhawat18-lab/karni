import { describe, expect, it, vi } from "vitest";
import {
  createAnimator,
  createCamera,
  createParticles,
  createPool,
  createRenderer,
  createTweens,
  damp,
  defineClips,
  inBack,
  inCubic,
  inExpo,
  inOutCubic,
  inOutQuad,
  inOutSine,
  inQuad,
  inSine,
  linear,
  outBack,
  outBounce,
  outCubic,
  outElastic,
  outExpo,
  outQuad,
  outSine,
  sheetFrames,
} from "../src/draw";
import { fakeImage, fakeView, ops, recordingContext } from "./fake-canvas";

const view = { width: 480, height: 270 };

describe("createCamera", () => {
  it("follows a box inside a dead zone, and only moves when it leaves it", () => {
    const camera = createCamera({ view, deadZone: { w: 100, h: 60 }, motion: 1 });
    const player = { x: 260, y: 130, w: 10, h: 10 };
    camera.follow(player);
    camera.update(1 / 60);
    // The centre of the box (265) is 25 from the camera's (240): inside the zone of 50 each side.
    expect(camera.x).toBe(240);
    player.x = 330;
    camera.update(1 / 60);
    // 335 is 45 past the zone's right edge (290): the camera moves by that.
    expect(camera.x).toBe(285);
    player.y = 300;
    camera.update(1 / 60);
    expect(camera.y).toBe(305 - 30);
  });

  it("puts the target off centre with an offset and catches up with smoothing", () => {
    const camera = createCamera({ view, offset: { x: -80, y: 0 }, smoothing: 10, motion: 1 });
    camera.follow({ x: 1000, y: 135 });
    camera.snap();
    expect(camera.x).toBe(1080);
    camera.follow({ x: 1100, y: 135 });
    camera.update(0.1);
    // One tenth of a second at rate 10: 1 - e^-1 of the way.
    expect(camera.x).toBeCloseTo(1080 + 100 * (1 - Math.exp(-1)));
    for (let i = 0; i < 60; i += 1) camera.update(0.05);
    expect(camera.x).toBeCloseTo(1180);
  });

  it("stays inside the bounds, centres a world smaller than the screen and allows an open end", () => {
    const camera = createCamera({ view, bounds: { x: 0, y: 0, w: 2000, h: 540 }, motion: 1 });
    camera.follow({ x: -500, y: -500 });
    camera.update(1 / 60);
    expect([camera.x, camera.y]).toEqual([240, 135]);
    camera.follow({ x: 5000, y: 5000 });
    camera.update(1 / 60);
    expect([camera.x, camera.y]).toEqual([1760, 405]);
    camera.bounds = { x: 0, y: 0, w: 300, h: 100 };
    camera.update(1 / 60);
    expect([camera.x, camera.y]).toEqual([150, 50]);
    camera.bounds = { x: 0, y: 0, w: Infinity, h: 270 };
    camera.follow({ x: 99999, y: 0 });
    camera.update(1 / 60);
    expect([camera.x, camera.y]).toEqual([99999, 135]);
  });

  it("zooms: it shows less of the world, and the bounds tighten", () => {
    const camera = createCamera({
      view,
      zoom: 2,
      bounds: { x: 0, y: 0, w: 480, h: 270 },
      motion: 1,
    });
    camera.follow({ x: 0, y: 0 });
    camera.update(1 / 60);
    expect([camera.width, camera.height]).toEqual([240, 135]);
    expect([camera.x, camera.y]).toEqual([120, 67.5]);
    expect([camera.left, camera.top]).toEqual([0, 0]);
    expect(camera.sees(230, 10, 5, 5)).toBe(true);
    expect(camera.sees(250, 10, 5, 5)).toBe(false);
  });

  it("maps between the world and the screen both ways", () => {
    const camera = createCamera({ view, x: 1000, y: 500, zoom: 1.5, motion: 1 });
    const point = { x: 0, y: 0 };
    camera.toScreen(1010, 520, point);
    expect(point).toEqual({ x: 255, y: 165 });
    camera.toWorld(point.x, point.y, point);
    expect(point.x).toBeCloseTo(1010);
    expect(point.y).toBeCloseTo(520);
  });

  it("shakes, fades out, keeps the stronger shake and scales it by the motion setting", () => {
    const camera = createCamera({ view, motion: 1 });
    camera.shake(10, 0.5);
    camera.update(0.01);
    const first = Math.hypot(camera.shakeX, camera.shakeY);
    expect(first).toBeGreaterThan(0);
    expect(Math.max(Math.abs(camera.shakeX), Math.abs(camera.shakeY))).toBeLessThanOrEqual(10);
    camera.shake(1, 0.1);
    for (let i = 0; i < 10; i += 1) camera.update(0.01);
    // The weak shake did not cut the strong one short: it still runs after 0.1 s.
    expect(Math.hypot(camera.shakeX, camera.shakeY)).toBeGreaterThan(0);
    for (let i = 0; i < 50; i += 1) camera.update(0.01);
    expect([camera.shakeX, camera.shakeY]).toEqual([0, 0]);
    camera.motion = 0;
    camera.shake(10, 0.5);
    camera.update(0.01);
    expect(Math.hypot(camera.shakeX, camera.shakeY)).toBe(0);
  });

  it("reads the browser's reduced-motion setting when the game sets none", () => {
    const matchMedia = vi.fn(() => ({ matches: true }) as MediaQueryList);
    vi.stubGlobal("matchMedia", matchMedia);
    try {
      expect(createCamera({ view }).motion).toBe(0.25);
      expect(createParticles().motion).toBe(0.25);
      expect(matchMedia).toHaveBeenCalledWith("(prefers-reduced-motion: reduce)");
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe("frame animation", () => {
  const frames = sheetFrames(fakeImage(80, 16), 16, 16);
  const clips = defineClips(frames, {
    idle: { frames: [0], fps: 1 },
    run: { frames: { from: 1, to: 3 }, fps: 10 },
    land: { frames: [4, 0], fps: 20, loop: false },
  });

  it("plays named clips at their rate, looping or not", () => {
    const ends: string[] = [];
    const animator = createAnimator(clips, "idle", (clip) => ends.push(clip));
    animator.play("run");
    expect(animator.sprite).toBe(frames[1]);
    animator.update(0.1);
    expect(animator.sprite).toBe(frames[2]);
    animator.update(0.25);
    // 0.35 s at 10 frames a second is frame 3 of a 3-frame loop: the first again.
    expect(animator.index).toBe(0);
    animator.play("run");
    expect(animator.index).toBe(0);
    animator.play("land");
    animator.update(0.2);
    expect(animator.sprite).toBe(frames[0]);
    expect(animator.done).toBe(true);
    expect(ends).toEqual(["land"]);
    animator.play("land", true);
    expect(animator.done).toBe(false);
    animator.speed = 2;
    animator.update(0.03);
    expect(animator.index).toBe(1);
  });

  it("refuses a clip that names a frame the sheet does not have", () => {
    expect(() => defineClips(frames, { bad: { frames: [9] } })).toThrow(/frame 9/);
    expect(() => defineClips(frames, { none: { frames: [] } })).toThrow(/no frames/);
  });
});

describe("easing", () => {
  const all = {
    linear,
    inQuad,
    outQuad,
    inOutQuad,
    inCubic,
    outCubic,
    inOutCubic,
    inSine,
    outSine,
    inOutSine,
    inExpo,
    outExpo,
    inBack,
    outBack,
    outElastic,
    outBounce,
  };

  it("starts at 0 and ends at 1", () => {
    for (const [name, ease] of Object.entries(all)) {
      expect(ease(0), name).toBeCloseTo(0, 3);
      expect(ease(1), name).toBeCloseTo(1, 3);
    }
  });

  it("has the shape its name says", () => {
    expect(inQuad(0.5)).toBeLessThan(0.5);
    expect(outQuad(0.5)).toBeGreaterThan(0.5);
    expect(inOutQuad(0.5)).toBeCloseTo(0.5);
    expect(inBack(0.2)).toBeLessThan(0);
    expect(Math.max(...[0.6, 0.7, 0.8, 0.9].map(outBack))).toBeGreaterThan(1);
  });

  it("damps the same way at any frame rate", () => {
    let fast = 0;
    for (let i = 0; i < 120; i += 1) fast = damp(fast, 100, 4, 1 / 120);
    let slow = 0;
    for (let i = 0; i < 30; i += 1) slow = damp(slow, 100, 4, 1 / 30);
    expect(fast).toBeCloseTo(slow, 6);
    expect(damp(5, 100, 0, 1)).toBe(100);
  });
});

describe("createTweens", () => {
  it("moves number properties with an easing, after a delay, and ends exactly", () => {
    const tweens = createTweens();
    const box = { x: 0, alpha: 1, name: "box" };
    const done = vi.fn();
    tweens.to(box, { x: 100, alpha: 0 }, 1, { ease: inQuad, delay: 0.5, onDone: done });
    tweens.update(0.5);
    expect(box.x).toBe(0);
    tweens.update(0.5);
    expect(box.x).toBeCloseTo(25);
    expect(box.alpha).toBeCloseTo(0.75);
    tweens.update(2);
    expect(box).toEqual({ x: 100, alpha: 0, name: "box" });
    expect(done).toHaveBeenCalledOnce();
    expect(tweens.size).toBe(0);
  });

  it("reads start values when it starts, so chained tweens pick up where the last ended", () => {
    const tweens = createTweens();
    const box = { y: 0 };
    tweens.to(box, { y: 10 }, 0.1, { onDone: () => tweens.to(box, { y: 30 }, 0.1) });
    tweens.update(0.1);
    expect(box.y).toBe(10);
    tweens.update(0.05);
    expect(box.y).toBeCloseTo(20);
  });

  it("repeats there and back, and cancels", () => {
    const tweens = createTweens();
    const box = { x: 0 };
    const tween = tweens.to(box, { x: 10 }, 1, { repeat: 1, yoyo: true });
    tweens.update(1.5);
    expect(box.x).toBeCloseTo(5);
    tweens.update(1);
    expect(box.x).toBe(0);
    expect(tween.done).toBe(true);
    const forever = tweens.to(box, { x: 10 }, 1, { repeat: Infinity });
    tweens.update(10.25);
    expect(box.x).toBeCloseTo(2.5);
    forever.cancel();
    tweens.update(0.5);
    expect(box.x).toBeCloseTo(2.5);
  });

  it("cancels every tween of a thing, waits on the game clock and clears", () => {
    const tweens = createTweens();
    const a = { x: 0 };
    const b = { x: 0 };
    tweens.to(a, { x: 1 }, 1);
    tweens.to(b, { x: 1 }, 1);
    tweens.cancelOf(a);
    const rang = vi.fn();
    tweens.wait(0.3, rang);
    tweens.update(0.2);
    expect(rang).not.toHaveBeenCalled();
    tweens.update(0.2);
    expect(rang).toHaveBeenCalledOnce();
    expect([a.x, b.x]).toEqual([0, 0.4]);
    tweens.clear();
    expect(tweens.size).toBe(0);
  });
});

describe("createPool", () => {
  it("hands out items, reuses given-back ones and stops at its max", () => {
    let made = 0;
    const pool = createPool({
      create: () => ({ id: (made += 1), live: false }),
      max: 2,
      prefill: 1,
    });
    expect(pool.made).toBe(1);
    const a = pool.acquire();
    const b = pool.acquire();
    expect(pool.acquire()).toBeNull();
    expect(pool.size).toBe(2);
    expect(a && pool.release(a)).toBe(true);
    expect(a && pool.release(a)).toBe(false);
    expect(pool.acquire()).toBe(a);
    expect(b).not.toBe(a);
    expect(made).toBe(2);
  });

  it("keeps the order of live items when some are given back", () => {
    const reset = vi.fn();
    const pool = createPool({ create: () => ({ n: 0 }), reset });
    for (let n = 1; n <= 5; n += 1) {
      const item = pool.acquire();
      if (item) item.n = n;
    }
    pool.retain((item) => item.n % 2 === 1);
    const seen: number[] = [];
    pool.forEach((item) => seen.push(item.n));
    expect(seen).toEqual([1, 3, 5]);
    expect(reset).toHaveBeenCalledTimes(2);
    pool.clear();
    expect(pool.size).toBe(0);
    expect(pool.made).toBe(5);
  });
});

describe("createParticles", () => {
  /** A repeatable random source. */
  const stepper = () => {
    let n = 0;
    return () => {
      n = (n + 0.37) % 1;
      return n;
    };
  };

  it("bursts, moves, fades and removes particles at the end of their life", () => {
    const particles = createParticles({ max: 100, random: stepper(), motion: 1 });
    const sparks = particles.emitter({ speed: 100, angle: 0, life: 1, size: 4, gravity: 0 });
    sparks.burst(10, 20, 5);
    expect(particles.count).toBe(5);
    particles.update(0.5);
    const { context, calls } = recordingContext();
    const renderer = createRenderer({ context, view: fakeView(1, 1), layers: ["fx"] });
    renderer.on("fx", (g) => particles.draw(g));
    renderer.render();
    const squares = ops(calls, "fillRect").slice(1);
    expect(squares).toHaveLength(5);
    // Half way: moved 50 to the right, half the size (shrinking to 0), half faded.
    expect(squares[0]).toMatchObject({ args: [59, 19, 2, 2], alpha: 0.5 });
    particles.update(0.6);
    expect(particles.count).toBe(0);
  });

  it("never passes its cap, and scales bursts and streams by the motion setting", () => {
    const particles = createParticles({ max: 10, random: stepper(), motion: 1 });
    const dust = particles.emitter({});
    dust.burst(0, 0, 50);
    expect(particles.count).toBe(10);
    particles.clear();
    particles.motion = 0.5;
    dust.burst(0, 0, 8);
    expect(particles.count).toBe(4);
    particles.clear();
    // A stream of 30 a second at half motion, over a second in 60 frames: 15.
    particles.motion = 0.5;
    for (let i = 0; i < 60; i += 1) dust.flow(0, 0, 30, 1 / 60);
    expect(particles.count).toBe(10);
    particles.clear();
    particles.motion = 0;
    dust.burst(0, 0, 8);
    expect(particles.count).toBe(0);
  });

  it("falls with gravity, slows with drag and draws circles with a blend", () => {
    const particles = createParticles({ max: 4, random: stepper(), motion: 1 });
    const ember = particles.emitter({
      speed: 0,
      life: 10,
      gravity: 100,
      drag: 0.5,
      shape: "circle",
      blend: "lighter",
      fade: false,
      colors: ["orange"],
    });
    ember.burst(0, 0, 1);
    particles.update(0.1);
    particles.update(0.1);
    const { context, calls } = recordingContext();
    const renderer = createRenderer({ context, view: fakeView(1, 1), layers: ["fx"] });
    renderer.on("fx", (g) => particles.draw(g));
    renderer.render();
    const arc = ops(calls, "arc")[0];
    // vy: 10 then (10 * 0.95 + 10): y = 1 + 1.95.
    expect(arc?.args[1]).toBeCloseTo(2.95);
    expect(ops(calls, "fill")[0]).toMatchObject({ fill: "orange", blend: "lighter", alpha: 1 });
  });
});
