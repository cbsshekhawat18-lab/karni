import { describe, expect, it, vi } from "vitest";
import {
  createCamera,
  createPainter,
  createRenderer,
  createSprite,
  sheetFrames,
  textStyle,
} from "../src/draw";
import { fakeImage, fakeView, must, ops, recordingContext } from "./fake-canvas";

describe("createRenderer", () => {
  it("draws the layers in order, whatever order they were filled in", () => {
    const { context, calls } = recordingContext();
    const renderer = createRenderer({
      context,
      view: fakeView(),
      layers: ["sky", "world", { name: "hud", screen: true }],
    });
    renderer.on("hud", (g) => g.rect(0, 0, 10, 10, "hud"));
    renderer.on("world", (g) => g.rect(0, 0, 10, 10, "world"));
    renderer.on("sky", (g) => g.rect(0, 0, 10, 10, "sky"));
    renderer.render();
    const fills = ops(calls, "fillRect").map((call) => call.fill);
    // The background first, then sky, world, hud.
    expect(fills).toEqual(["#000000", "sky", "world", "hud"]);
  });

  it("follows a changed order, and keeps the list order on ties", () => {
    const { context, calls } = recordingContext();
    const renderer = createRenderer({
      context,
      view: fakeView(),
      background: null,
      layers: ["a", "b", { name: "c", order: 1 }],
    });
    for (const name of ["a", "b", "c"] as const) renderer.on(name, (g) => g.rect(0, 0, 1, 1, name));
    renderer.render();
    expect(ops(calls, "fillRect").map((call) => call.fill)).toEqual(["a", "b", "c"]);
    calls.length = 0;
    renderer.layer("a").order = 5;
    renderer.render();
    expect(ops(calls, "fillRect").map((call) => call.fill)).toEqual(["b", "c", "a"]);
    expect(ops(calls, "clearRect")).toHaveLength(1);
  });

  it("maps game units through the view: scale, pixel ratio and the letterbox offset", () => {
    const { context, calls } = recordingContext();
    const renderer = createRenderer({
      context,
      view: fakeView(2, 1.5, 10, 0),
      layers: [{ name: "hud", screen: true }],
    });
    renderer.on("hud", (g) => g.rect(1, 1, 1, 1, "x"));
    renderer.render();
    const rect = ops(calls, "fillRect").find((call) => call.fill === "x");
    expect(rect?.transform).toEqual([3, 0, 0, 3, 15, 0]);
    // The frame is clipped to the game area.
    expect(ops(calls, "rect")[0]?.args).toEqual([0, 0, 480, 270]);
    expect(ops(calls, "clip")).toHaveLength(1);
  });

  it("moves world layers with the camera and screen layers not at all", () => {
    const { context, calls } = recordingContext();
    const view = fakeView(1, 1);
    const camera = createCamera({ view, x: 340, y: 135, motion: 1 });
    const renderer = createRenderer({
      context,
      view,
      camera,
      layers: ["world", { name: "far", parallax: 0.5 }, { name: "hud", screen: true }],
    });
    renderer.on("world", (g) => g.rect(300, 100, 10, 10, "world"));
    renderer.on("far", (g) => g.rect(300, 100, 10, 10, "far"));
    renderer.on("hud", (g) => g.rect(0, 0, 10, 10, "hud"));
    renderer.render();
    const at = (fill: string) =>
      ops(calls, "fillRect").find((call) => call.fill === fill)?.transform;
    // The camera is 100 units right of the start: the world shifts 100 left, the far layer 50.
    expect(at("world")).toEqual([1, 0, 0, 1, -100, 0]);
    expect(at("far")).toEqual([1, 0, 0, 1, -50, 0]);
    expect(at("hud")).toEqual([1, 0, 0, 1, 0, 0]);
  });

  it("zooms world layers about the centre of the screen", () => {
    const { context, calls } = recordingContext();
    const view = fakeView(1, 1);
    const camera = createCamera({ view, zoom: 2 });
    const renderer = createRenderer({ context, view, camera, layers: ["world"] });
    let shown: number[] = [];
    renderer.on("world", (g) => {
      shown = [g.left, g.top, g.width, g.height];
      g.rect(200, 100, 1, 1, "w");
      g.rect(0, 0, 1, 1, "outside");
    });
    renderer.render();
    // At zoom 2 the screen shows a quarter of the world, centred.
    expect(shown).toEqual([120, 67.5, 240, 135]);
    expect(renderer.stats.culled).toBe(1);
    const transform = ops(calls, "fillRect").find((call) => call.fill === "w")?.transform;
    expect(transform).toEqual([2, 0, 0, 2, -240, -135]);
  });

  it("culls what is off screen and counts it", () => {
    const { context, calls } = recordingContext();
    const view = fakeView(1, 1);
    const camera = createCamera({ view });
    const renderer = createRenderer({ context, view, camera, layers: ["world"] });
    renderer.on("world", (g) => {
      g.rect(10, 10, 5, 5, "on");
      g.rect(-50, 10, 5, 5, "left");
      g.rect(1000, 10, 5, 5, "right");
      g.circle(478, 100, 4, "edge");
      g.circle(600, 100, 4, "far");
    });
    renderer.render();
    expect(renderer.stats).toEqual({ drawn: 2, culled: 3, calls: 1 });
    expect(ops(calls, "fillRect").map((call) => call.fill)).toEqual(["#000000", "on"]);
    expect(ops(calls, "arc")).toHaveLength(1);
  });

  it("keeps drawing the other layers when a draw function throws", () => {
    const { context, calls } = recordingContext();
    const onError = vi.fn();
    const renderer = createRenderer({ context, view: fakeView(), layers: ["a", "b"], onError });
    renderer.on("a", () => {
      throw new Error("broken");
    });
    renderer.on("b", (g) => g.rect(0, 0, 1, 1, "b"));
    renderer.render();
    expect(onError).toHaveBeenCalledWith(expect.any(Error), "a");
    expect(ops(calls, "fillRect").map((call) => call.fill)).toContain("b");
    // Every save of the frame is restored.
    expect(ops(calls, "save")).toHaveLength(ops(calls, "restore").length);
  });

  it("removes a draw function, hides a layer and refuses an unknown one", () => {
    const { context, calls } = recordingContext();
    const renderer = createRenderer({ context, view: fakeView(), layers: ["a", "b"] });
    const off = renderer.on("a", (g) => g.rect(0, 0, 1, 1, "a"));
    renderer.on("b", (g) => g.rect(0, 0, 1, 1, "b"));
    off();
    renderer.layer("b").visible = false;
    renderer.render();
    expect(ops(calls, "fillRect").map((call) => call.fill)).toEqual(["#000000"]);
    expect(() => renderer.layer("c" as "a")).toThrow(/no layer "c"/);
    expect(() => createRenderer({ context, view: fakeView(), layers: ["a", "a"] })).toThrow(
      /named twice/,
    );
  });

  it("gives each layer its opacity and resets the painter's between draw functions", () => {
    const { context, calls } = recordingContext();
    const renderer = createRenderer({
      context,
      view: fakeView(),
      layers: [{ name: "fog", alpha: 0.5 }],
    });
    renderer.on("fog", (g) => {
      g.alpha = 0.5;
      g.rect(0, 0, 1, 1, "first");
    });
    renderer.on("fog", (g) => g.rect(0, 0, 1, 1, "second"));
    renderer.render();
    const alpha = (fill: string) =>
      ops(calls, "fillRect").find((call) => call.fill === fill)?.alpha;
    expect(alpha("first")).toBe(0.25);
    expect(alpha("second")).toBe(0.5);
  });
});

describe("the painter", () => {
  it("draws shapes with their style", () => {
    const { context, calls } = recordingContext();
    const g = createPainter(context);
    g.strokeRect(0, 0, 4, 4, "red", 2);
    g.line(0, 0, 10, 10, "blue", 3);
    g.poly([0, 0, 10, 0, 5, 8], "green", "black", 1);
    g.strokeCircle(5, 5, 2, "pink");
    expect(ops(calls, "strokeRect")[0]).toMatchObject({ args: [0, 0, 4, 4], stroke: "red" });
    expect(ops(calls, "lineTo").map((call) => call.args)).toEqual([
      [10, 10],
      [10, 0],
      [5, 8],
    ]);
    expect(ops(calls, "fill")[0]?.fill).toBe("green");
    expect(ops(calls, "stroke").map((call) => call.stroke)).toEqual(["blue", "black", "pink"]);
    expect(g.drawn).toBe(4);
    // A polygon needs three points.
    g.poly([0, 0, 1, 1], "green");
    expect(g.drawn).toBe(4);
  });

  it("sets a text style's font once, not on every draw", () => {
    const { context, calls } = recordingContext();
    const g = createPainter(context);
    const hud = textStyle({ font: "14px system-ui", fill: "#fff", stroke: "#000" });
    g.text("Score 10", 4, 4, hud);
    g.text("Best 20", 4, 20, hud);
    const fonts = calls.filter((call) => call.op === "fillText").map((call) => call.font);
    expect(fonts).toEqual(["14px system-ui", "14px system-ui"]);
    expect(ops(calls, "font")).toHaveLength(1);
    // Reading the raw context may change the font behind the painter's back: it is set again.
    g.ctx.font = "30px serif";
    g.text("Best 20", 4, 20, hud);
    expect(ops(calls, "font").map((call) => call.args[0])).toEqual([
      "14px system-ui",
      "30px serif",
      "14px system-ui",
    ]);
    expect(ops(calls, "strokeText")).toHaveLength(3);
    // A short line with no wrap is drawn without measuring.
    expect(ops(calls, "measureText")).toHaveLength(0);
  });

  it("wraps text at the style's width and measures each string once", () => {
    const { context, calls } = recordingContext();
    const g = createPainter(context);
    const body = textStyle({ font: "10px serif", wrap: 60, lineHeight: 12 });
    const layout = g.measure("one two three four", body);
    // Six units a character in the fake: "one two" is 42, "one two three" is 78.
    expect(layout.lines).toEqual(["one two", "three four"]);
    expect(layout.height).toBe(24);
    const measured = ops(calls, "measureText").length;
    g.text("one two three four", 0, 0, body);
    g.text("one two three four", 0, 0, body);
    expect(ops(calls, "measureText")).toHaveLength(measured);
    expect(ops(calls, "fillText").map((call) => call.args)).toEqual([
      ["one two", 0, 0],
      ["three four", 0, 12],
      ["one two", 0, 0],
      ["three four", 0, 12],
    ]);
    expect(body.cached).toBe(1);
    body.clearCache();
    expect(body.cached).toBe(0);
  });

  it("bounds the layout cache", () => {
    const { context } = recordingContext();
    const style = textStyle({ font: "10px serif", cacheSize: 3 });
    for (let i = 0; i < 5; i += 1) style.layout(context, `line ${i}`);
    expect(style.cached).toBeLessThanOrEqual(3);
  });

  it("culls text on a world layer by its measured box", () => {
    const { context, calls } = recordingContext();
    const view = fakeView(1, 1);
    const renderer = createRenderer({
      context,
      view,
      camera: createCamera({ view }),
      layers: ["w"],
    });
    const label = textStyle({ font: "10px serif", align: "right" });
    renderer.on("w", (g) => {
      g.text("far away", 900, 10, label);
      // Right-aligned at x 20: the box runs from -4 to 20, partly on screen.
      g.text("near", 20, 10, label);
    });
    renderer.render();
    expect(ops(calls, "fillText").map((call) => call.args[0])).toEqual(["near"]);
  });

  it("draws a sprite's region at its anchor, and turned or flipped about it", () => {
    const { context, calls } = recordingContext();
    const view = fakeView(1, 1);
    const renderer = createRenderer({ context, view, layers: [{ name: "s", screen: true }] });
    const image = fakeImage(64, 16);
    const frames = sheetFrames(image, 16, 16, { anchor: [0.5, 1] });
    expect(frames).toHaveLength(4);
    renderer.on("s", (g) => {
      g.sprite(must(frames[2]), 100, 50);
      g.sprite(must(frames[0]), 100, 50, -1, 1, Math.PI / 2);
    });
    renderer.render();
    const draws = ops(calls, "drawImage");
    expect(draws[0]?.args).toEqual([32, 0, 16, 16, 92, 34, 16, 16]);
    // The turned one: drawn about its anchor with a transform of its own, then the layer's again.
    expect(draws[1]?.args).toEqual([0, 0, 16, 16, -8, -16, 16, 16]);
    const turned = draws[1]?.transform ?? [];
    expect(turned.map((n) => Math.round(n * 1000) / 1000 + 0)).toEqual([0, -1, -1, 0, 100, 50]);
    expect(calls.at(-2)?.op).toBe("setTransform");
  });

  it("skips a sprite whose image has not loaded", () => {
    const { context, calls } = recordingContext();
    const g = createPainter(context);
    const image = document.createElement("img");
    const sprite = createSprite(image, { w: 8, h: 8 });
    expect(g.sprite(sprite, 0, 0)).toBe(false);
    expect(ops(calls, "drawImage")).toHaveLength(0);
  });

  it("cuts sheets with a margin and spacing, and scales a sprite", () => {
    const image = fakeImage(2 + 3 * 10 + 2 * 1 + 2, 14);
    const frames = sheetFrames(image, 10, 10, { margin: 2, spacing: 1, scale: 2 });
    expect(frames.map((frame) => frame.sx)).toEqual([2, 13, 24]);
    expect(frames[0]).toMatchObject({ sy: 2, w: 20, h: 20, ax: 0, ay: 0 });
    const whole = createSprite(fakeImage(30, 20), { anchor: [0.5, 0.5] });
    expect(whole).toMatchObject({ sw: 30, sh: 20, ax: 15, ay: 10 });
  });
});
