import { describe, expect, it, vi } from "vitest";
import { createFixedStep, createInput, createLoop, createView, pauseOnHidden } from "../src";

describe("createFixedStep", () => {
  it("runs whole steps and returns the leftover fraction", () => {
    const fixed = createFixedStep({ step: 0.01, maxSteps: 10 });
    const steps: number[] = [];
    const alpha = fixed.advance(0.035, (step) => steps.push(step));
    expect(steps).toEqual([0.01, 0.01, 0.01]);
    expect(alpha).toBeCloseTo(0.5);
    fixed.advance(0.005, (step) => steps.push(step));
    expect(steps).toHaveLength(4);
  });

  it("caps the steps of one frame and drops the backlog (no spiral of death)", () => {
    const fixed = createFixedStep({ step: 0.01, maxSteps: 5 });
    let count = 0;
    fixed.advance(1, () => {
      count += 1;
    });
    expect(count).toBe(5);
    expect(fixed.dropped).toBeCloseTo(0.95);
    count = 0;
    fixed.advance(0.01, () => {
      count += 1;
    });
    expect(count).toBe(1);
  });

  it("ignores negative and non-finite times", () => {
    const fixed = createFixedStep();
    let count = 0;
    fixed.advance(-1, () => (count += 1));
    fixed.advance(Number.NaN, () => (count += 1));
    expect(count).toBe(0);
    expect(() => createFixedStep({ step: 0 })).toThrow();
  });
});

describe("createLoop", () => {
  const frames = (): {
    request: (callback: (time: number) => void) => number;
    cancel: (handle: number) => void;
    run: (time: number) => void;
  } => {
    let pending: ((time: number) => void) | null = null;
    return {
      request: (callback) => {
        pending = callback;
        return 1;
      },
      cancel: () => {
        pending = null;
      },
      run: (time) => {
        const callback = pending;
        pending = null;
        callback?.(time);
      },
    };
  };

  it("clamps the frame time and calls update, render and afterFrame", () => {
    const raf = frames();
    const log: string[] = [];
    const loop = createLoop({
      update: (dt) => log.push(`update:${dt.toFixed(3)}`),
      render: (_alpha, dt) => log.push(`render:${dt.toFixed(3)}`),
      afterFrame: () => log.push("after"),
      maxDt: 0.05,
      requestFrame: raf.request,
      cancelFrame: raf.cancel,
    });
    loop.start();
    raf.run(1000);
    raf.run(1016);
    raf.run(3000); // a stall of two seconds is clamped
    expect(log).toEqual([
      "update:0.000",
      "render:0.000",
      "after",
      "update:0.016",
      "render:0.016",
      "after",
      "update:0.050",
      "render:0.050",
      "after",
    ]);
    expect(loop.frame).toBe(3);
    loop.stop();
    expect(loop.running).toBe(false);
  });

  it("runs a fixed step when asked", () => {
    const steps: number[] = [];
    const alphas: number[] = [];
    const loop = createLoop({
      step: 0.01,
      update: (dt) => steps.push(dt),
      render: (alpha) => alphas.push(alpha),
      requestFrame: () => 0,
      cancelFrame: () => undefined,
    });
    loop.tick(0.025);
    expect(steps).toEqual([0.01, 0.01]);
    expect(alphas[0]).toBeCloseTo(0.5);
  });

  it("keeps a press made in a frame that ran no fixed step for the next step (a 120 Hz screen)", () => {
    const input = createInput();
    const seen: boolean[] = [];
    const loop = createLoop({
      step: 1 / 60,
      update: () => seen.push(input.pressed("Space")),
      afterFrame: () => input.endFrame(),
      requestFrame: () => 0,
      cancelFrame: () => undefined,
    });
    input.press("Space");
    input.release("Space");
    loop.tick(1 / 120); // no step: the press waits
    expect(seen).toEqual([]);
    expect(loop.fixed?.lastSteps).toBe(0);
    loop.tick(1 / 120); // one step sees it, then the edge is cleared
    loop.tick(1 / 120);
    loop.tick(1 / 120);
    expect(seen).toEqual([true, false]);
    loop.pause("menu");
    input.press("KeyA");
    loop.tick(1 / 120); // paused: the frame clears what was pressed meanwhile
    expect(input.pressed("KeyA")).toBe(false);
    input.destroy();
  });

  it("pauses for named reasons and resumes when every reason is lifted", () => {
    let updates = 0;
    let renders = 0;
    const events: string[] = [];
    const loop = createLoop({
      update: () => (updates += 1),
      render: () => (renders += 1),
      requestFrame: () => 0,
      cancelFrame: () => undefined,
    });
    loop.on("pause", (reason) => events.push(`pause:${reason}`));
    loop.on("resume", () => events.push("resume"));
    loop.pause("hidden");
    loop.pause("ad");
    loop.tick(0.016);
    expect(updates).toBe(0);
    expect(renders).toBe(1); // the pause screen is still drawn
    loop.resume("hidden");
    expect(loop.paused).toBe(true);
    loop.resume("ad");
    loop.tick(0.016);
    expect(updates).toBe(1);
    expect(events).toEqual(["pause:hidden", "resume"]);
  });

  it("keeps running after a frame throws", () => {
    const errors: string[] = [];
    let n = 0;
    const loop = createLoop({
      update: () => {
        n += 1;
        if (n === 1) throw new Error("bad frame");
      },
      onError: (_error, phase) => errors.push(phase),
      requestFrame: () => 0,
      cancelFrame: () => undefined,
    });
    loop.tick(0.016);
    loop.tick(0.016);
    expect(n).toBe(2);
    expect(errors).toEqual(["update"]);
  });

  it("logs the first frame errors to the console by default", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const loop = createLoop({
      update: () => {
        throw new Error("bad");
      },
      requestFrame: () => 0,
      cancelFrame: () => undefined,
    });
    for (let i = 0; i < 20; i += 1) loop.tick(0.016);
    expect(spy).toHaveBeenCalledTimes(10);
  });
});

describe("pauseOnHidden", () => {
  it("pauses on a hidden tab and on blur, as separate reasons", () => {
    const log: string[] = [];
    const target = {
      pause: (reason: string) => log.push(`pause:${reason}`),
      resume: (reason: string) => log.push(`resume:${reason}`),
    };
    let state: DocumentVisibilityState = "visible";
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => state });
    const off = pauseOnHidden(target);
    state = "hidden";
    document.dispatchEvent(new Event("visibilitychange"));
    state = "visible";
    document.dispatchEvent(new Event("visibilitychange"));
    window.dispatchEvent(new Event("blur"));
    window.dispatchEvent(new Event("focus"));
    off();
    window.dispatchEvent(new Event("blur"));
    expect(log).toEqual(["pause:hidden", "resume:hidden", "pause:blur", "resume:blur"]);
  });

  it("can leave blur alone", () => {
    const log: string[] = [];
    const off = pauseOnHidden(
      { pause: (r) => log.push(r), resume: (r) => log.push(r) },
      { blur: false },
    );
    window.dispatchEvent(new Event("blur"));
    off();
    expect(log).toEqual([]);
  });
});

describe("createView", () => {
  const setup = (width: number, height: number): HTMLCanvasElement => {
    const parent = document.createElement("div");
    parent.getBoundingClientRect = () =>
      ({ width, height, left: 0, top: 0, right: width, bottom: height }) as DOMRect;
    const canvas = document.createElement("canvas");
    canvas.getBoundingClientRect = () =>
      ({ width, height, left: 10, top: 20, right: width, bottom: height }) as DOMRect;
    parent.appendChild(canvas);
    document.body.appendChild(parent);
    return canvas;
  };

  it("caps the pixel ratio, lower on touch devices", () => {
    const canvas = setup(400, 300);
    const desk = createView({ canvas, devicePixelRatio: () => 3, isTouch: () => false });
    expect(desk.dpr).toBe(2);
    expect(canvas.width).toBe(800);
    expect(canvas.style.width).toBe("400px");
    desk.destroy();
    const phone = createView({ canvas, devicePixelRatio: () => 3, isTouch: () => true });
    expect(phone.dpr).toBe(1.5);
    expect(canvas.height).toBe(450);
    const custom = createView({
      canvas,
      devicePixelRatio: () => 3,
      touchMaxDpr: 2.5,
      isTouch: () => true,
    });
    expect(custom.dpr).toBe(2.5);
  });

  it("letterboxes a virtual resolution and maps pointer positions into it", () => {
    const canvas = setup(800, 400);
    const view = createView({ canvas, width: 400, height: 400, devicePixelRatio: () => 1 });
    expect(view.scale).toBe(1);
    expect(view.offsetX).toBe(200);
    expect(view.offsetY).toBe(0);
    expect(view.toGame(10 + 200 + 100, 20 + 50)).toEqual({ x: 100, y: 50 });
    const calls: number[][] = [];
    view.apply({
      setTransform: (...args: number[]) => calls.push(args),
    } as unknown as CanvasRenderingContext2D);
    expect(calls).toEqual([[1, 0, 0, 1, 200, 0]]);
  });

  it("covers instead when asked, and uses CSS pixels in native mode", () => {
    const canvas = setup(800, 400);
    const cover = createView({
      canvas,
      width: 400,
      height: 400,
      fit: "cover",
      devicePixelRatio: () => 1,
    });
    expect(cover.scale).toBe(2);
    expect(cover.offsetY).toBe(-200);
    const native = createView({ canvas, devicePixelRatio: () => 2 });
    expect([native.width, native.height, native.scale]).toEqual([800, 400, 1]);
  });

  it("measures again on a window resize and tells listeners", () => {
    let width = 300;
    const parent = document.createElement("div");
    parent.getBoundingClientRect = () => ({ width, height: 200, left: 0, top: 0 }) as DOMRect;
    const canvas = document.createElement("canvas");
    parent.appendChild(canvas);
    const view = createView({ canvas, devicePixelRatio: () => 1 });
    const seen: number[] = [];
    view.onResize((state) => seen.push(state.cssWidth));
    width = 500;
    window.dispatchEvent(new Event("resize"));
    expect(view.cssWidth).toBe(500);
    expect(seen).toEqual([500]);
    view.destroy();
    width = 600;
    window.dispatchEvent(new Event("resize"));
    expect(view.cssWidth).toBe(500);
  });
});
