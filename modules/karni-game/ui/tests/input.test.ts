import { afterEach, describe, expect, it } from "vitest";
import { POINTER, STICK, createInput, createVirtualStick, type Input } from "../src";

const key = (
  type: "keydown" | "keyup",
  code: string,
  init: KeyboardEventInit = {},
): KeyboardEvent => {
  const event = new KeyboardEvent(type, { code, bubbles: true, cancelable: true, ...init });
  window.dispatchEvent(event);
  return event;
};

const pointer = (
  target: EventTarget,
  type: "pointerdown" | "pointermove" | "pointerup",
  x: number,
  y: number,
  id = 1,
  pointerType = "mouse",
): void => {
  const event = new MouseEvent(type, { clientX: x, clientY: y, bubbles: true });
  Object.defineProperty(event, "pointerId", { value: id });
  Object.defineProperty(event, "pointerType", { value: pointerType });
  target.dispatchEvent(event);
};

let input: Input | null = null;
afterEach(() => {
  input?.destroy();
  input = null;
});

describe("createInput", () => {
  it("reads held, pressed and released per action, edges for one frame", () => {
    input = createInput({ bindings: { jump: ["Space", "ArrowUp"] } });
    key("keydown", "Space");
    expect(input.pressed("jump")).toBe(true);
    expect(input.held("jump")).toBe(true);
    expect(input.held("Space")).toBe(true);
    input.endFrame();
    expect(input.pressed("jump")).toBe(false);
    expect(input.held("jump")).toBe(true);
    key("keydown", "Space", { repeat: true });
    expect(input.pressed("jump")).toBe(false);
    key("keyup", "Space");
    expect(input.released("jump")).toBe(true);
    expect(input.held("jump")).toBe(false);
    input.endFrame();
    expect(input.released("jump")).toBe(false);
  });

  it("keeps a tap shorter than a frame as pressed", () => {
    input = createInput({ bindings: { jump: ["Space"] } });
    key("keydown", "Space");
    key("keyup", "Space");
    expect(input.pressed("jump")).toBe(true);
    expect(input.released("jump")).toBe(true);
    expect(input.held("jump")).toBe(false);
  });

  it("stops the page scrolling on Space and the arrows, and ignores typing", () => {
    input = createInput();
    expect(key("keydown", "ArrowDown").defaultPrevented).toBe(true);
    expect(key("keydown", "KeyQ").defaultPrevented).toBe(false);
    const field = document.createElement("input");
    document.body.appendChild(field);
    field.dispatchEvent(new KeyboardEvent("keydown", { code: "KeyW", bubbles: true }));
    expect(input.held("KeyW")).toBe(false);
    field.remove();
  });

  it("treats the primary pointer as the Pointer key and records taps in game units", () => {
    const canvas = document.createElement("canvas");
    document.body.appendChild(canvas);
    input = createInput({
      target: canvas,
      view: { toGame: (x, y) => ({ x: x / 2, y: y / 2 }) },
      bindings: { jump: ["Space", POINTER] },
    });
    expect(canvas.style.touchAction).toBe("none");
    pointer(canvas, "pointerdown", 100, 40, 1, "touch");
    expect(input.pressed("jump")).toBe(true);
    expect(input.touch).toBe(true);
    expect(input.taps).toEqual([{ x: 50, y: 20 }]);
    expect(input.pointer).toMatchObject({ x: 50, y: 20, down: true });
    pointer(canvas, "pointermove", 120, 40, 1, "touch");
    expect(input.pointer?.x).toBe(60);
    input.endFrame();
    expect(input.taps).toEqual([]);
    pointer(canvas, "pointerup", 120, 40, 1, "touch");
    expect(input.released("jump")).toBe(true);
    expect(input.pointers.size).toBe(0);
    canvas.remove();
  });

  it("holds Pointer until the last finger lifts", () => {
    const canvas = document.createElement("canvas");
    input = createInput({ target: canvas });
    pointer(canvas, "pointerdown", 0, 0, 1, "touch");
    pointer(canvas, "pointerdown", 10, 0, 2, "touch");
    pointer(canvas, "pointerup", 0, 0, 1, "touch");
    expect(input.held(POINTER)).toBe(true);
    pointer(canvas, "pointerup", 10, 0, 2, "touch");
    expect(input.held(POINTER)).toBe(false);
  });

  it("runs first-gesture callbacks once, inside the first gesture", () => {
    input = createInput();
    const calls: string[] = [];
    input.onFirstGesture(() => calls.push("a"));
    const off = input.onFirstGesture(() => calls.push("b"));
    off();
    expect(calls).toEqual([]);
    key("keydown", "KeyA");
    key("keydown", "KeyB");
    expect(calls).toEqual(["a"]);
    input.onFirstGesture(() => calls.push("late"));
    expect(calls).toEqual(["a", "late"]);
  });

  it("lets go of everything on blur, and takes presses by hand", () => {
    input = createInput({ bindings: { left: ["ArrowLeft", "TouchLeft"] } });
    key("keydown", "ArrowLeft");
    input.press("TouchLeft");
    window.dispatchEvent(new Event("blur"));
    expect(input.held("left")).toBe(false);
    expect(input.released("left")).toBe(true);
    input.bind("left", ["KeyA"]);
    key("keydown", "KeyA");
    expect(input.held("left")).toBe(true);
  });
});

describe("createVirtualStick", () => {
  it("grabs a touch in its zone, reports deflection and presses the stick codes", () => {
    const canvas = document.createElement("canvas");
    input = createInput({
      target: canvas,
      bindings: { right: ["ArrowRight", STICK.right], jump: [POINTER] },
    });
    const stick = createVirtualStick(input, {
      radius: 50,
      area: () => ({ width: 400, height: 300 }),
    });
    pointer(canvas, "pointerdown", 100, 200, 7, "touch");
    expect(stick.active).toBe(true);
    expect(input.pressed("jump")).toBe(false); // the stick owns this finger
    pointer(canvas, "pointermove", 140, 200, 7, "touch");
    expect(stick.x).toBeCloseTo(0.8);
    expect(input.held("right")).toBe(true);
    pointer(canvas, "pointermove", 300, 200, 7, "touch");
    expect(stick.x).toBe(1);
    expect(stick.knob).toEqual({ x: 150, y: 200 });
    pointer(canvas, "pointermove", 103, 200, 7, "touch");
    expect(stick.x).toBe(0); // inside the dead zone
    pointer(canvas, "pointerup", 103, 200, 7, "touch");
    expect(stick.active).toBe(false);
    expect(input.held("right")).toBe(false);
    stick.destroy();
  });

  it("leaves the right half and mouse clicks to the game", () => {
    const canvas = document.createElement("canvas");
    input = createInput({ target: canvas, bindings: { jump: [POINTER] } });
    const stick = createVirtualStick(input, { area: () => ({ width: 400, height: 300 }) });
    pointer(canvas, "pointerdown", 300, 100, 1, "touch");
    expect(stick.active).toBe(false);
    expect(input.pressed("jump")).toBe(true);
    pointer(canvas, "pointerup", 300, 100, 1, "touch");
    pointer(canvas, "pointerdown", 50, 100, 2, "mouse");
    expect(stick.active).toBe(false);
  });

  it("draws a ring and a knob while active", () => {
    const canvas = document.createElement("canvas");
    input = createInput({ target: canvas });
    const stick = createVirtualStick(input, { area: () => ({ width: 400, height: 300 }) });
    const calls: string[] = [];
    const context = new Proxy(
      {},
      {
        get: (_target, name) => () => calls.push(String(name)),
        set: () => true,
      },
    ) as CanvasRenderingContext2D;
    stick.draw(context);
    expect(calls).toEqual([]);
    pointer(canvas, "pointerdown", 50, 100, 3, "touch");
    stick.draw(context);
    expect(calls).toContain("arc");
  });
});
