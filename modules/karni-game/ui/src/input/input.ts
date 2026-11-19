import { createEmitter } from "../internal/emitter";

/** The pseudo key code of the primary pointer (mouse button, finger, pen). */
export const POINTER = "Pointer";

export interface PointerState {
  readonly id: number;
  /** Position in game units (through the view), or CSS pixels inside the target. */
  readonly x: number;
  readonly y: number;
  readonly down: boolean;
  readonly type: string;
  /** A control (the virtual stick) owns this pointer, so it is not the "Pointer" key. */
  readonly claimed: boolean;
}

export interface InputOptions {
  /** Where pointer events are read: the canvas. Default the window. */
  target?: HTMLElement | Window;
  /** Where key events are read. Default the window. */
  keyTarget?: HTMLElement | Window;
  /** Maps a pointer's client position to game units. Default: CSS pixels inside the target. */
  view?: { toGame(clientX: number, clientY: number): { x: number; y: number } };
  /** Actions and the key codes (`KeyboardEvent.code`, or "Pointer") that trigger each. */
  bindings?: Record<string, readonly string[]>;
  /**
   * Codes whose default the browser must not run (page scroll inside a
   * portal's frame). Default Space and the arrow keys.
   */
  preventDefault?: readonly string[];
  /** Ignore keys typed into a text field. Default true. */
  ignoreTyping?: boolean;
}

export interface Input {
  /** Is the action or code down now? */
  held(name: string): boolean;
  /** Did it go down during this frame? */
  pressed(name: string): boolean;
  /** Did it come up during this frame? */
  released(name: string): boolean;
  /** The primary pointer, or null before any pointer moved over the target. */
  readonly pointer: PointerState | null;
  /** Every pointer down now, by id (several fingers). */
  readonly pointers: ReadonlyMap<number, PointerState>;
  /** Where pointers went down during this frame, in game units. */
  readonly taps: readonly { x: number; y: number }[];
  /** The last input came from a touch screen. */
  readonly touch: boolean;
  /** Clear this frame's edge flags. Call once per frame, after the update (the loop's afterFrame). */
  endFrame(): void;
  /**
   * Run `callback` on the player's first tap, click or key, inside that
   * event (what browsers require to start audio). After it, at once.
   */
  onFirstGesture(callback: () => void): () => void;
  /** Called when a pointer goes down, before it counts as "Pointer": return true to own it. */
  onPointerDown(listener: (pointer: PointerState) => unknown): () => void;
  onPointerMove(listener: (pointer: PointerState) => void): () => void;
  onPointerUp(listener: (pointer: PointerState) => void): () => void;
  /** Press and release a code by hand: on-screen buttons, the virtual stick, tests. */
  press(code: string): void;
  release(code: string): void;
  /** Let go of everything (the window lost focus, an ad started). */
  releaseAll(): void;
  /** Change an action's codes. */
  bind(action: string, codes: readonly string[]): void;
  destroy(): void;
}

interface PointerEvents {
  down: PointerState;
  move: PointerState;
  up: PointerState;
}

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.isContentEditable ||
    target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    target instanceof HTMLSelectElement
  );
}

/**
 * Keyboard, mouse, touch and pen in one place, with held, pressed and
 * released flags per action. Pressed and released last one frame: a tap
 * shorter than a frame still reads as pressed.
 */
export function createInput(options: InputOptions = {}): Input {
  const target = options.target ?? window;
  const keyTarget = options.keyTarget ?? window;
  const bindings = new Map<string, readonly string[]>(Object.entries(options.bindings ?? {}));
  const prevent = new Set(
    options.preventDefault ?? ["Space", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"],
  );
  const ignoreTyping = options.ignoreTyping ?? true;
  const pointerEvents = createEmitter<PointerEvents>();
  const downListeners = new Set<(pointer: PointerState) => unknown>();

  const down = new Set<string>();
  const pressedNow = new Set<string>();
  const releasedNow = new Set<string>();
  const pointers = new Map<number, PointerState>();
  let primary: PointerState | null = null;
  let taps: { x: number; y: number }[] = [];
  let touch = false;

  let gestured = false;
  const gestureCallbacks = new Set<() => void>();

  const codesOf = (name: string): readonly string[] => [name, ...(bindings.get(name) ?? [])];

  const press = (code: string): void => {
    if (down.has(code)) return;
    down.add(code);
    pressedNow.add(code);
  };
  const release = (code: string): void => {
    if (!down.delete(code)) return;
    releasedNow.add(code);
  };

  const position = (event: PointerEvent): { x: number; y: number } => {
    if (options.view) return options.view.toGame(event.clientX, event.clientY);
    if (target instanceof HTMLElement) {
      const box = target.getBoundingClientRect();
      return { x: event.clientX - box.left, y: event.clientY - box.top };
    }
    return { x: event.clientX, y: event.clientY };
  };

  const GESTURES = ["pointerdown", "pointerup", "keydown", "touchend", "click"] as const;
  const gesture = (): void => {
    if (gestured) return;
    gestured = true;
    for (const callback of [...gestureCallbacks]) {
      try {
        callback();
      } catch (error) {
        console.error("[karni-game] a first-gesture callback threw", error);
      }
    }
    gestureCallbacks.clear();
    for (const type of GESTURES) window.removeEventListener(type, gesture, true);
  };
  for (const type of GESTURES) window.addEventListener(type, gesture, true);

  const onKeyDown = (event: Event): void => {
    const key = event as KeyboardEvent;
    if (ignoreTyping && isTyping(key.target)) return;
    if (prevent.has(key.code)) key.preventDefault();
    touch = false;
    if (key.repeat) return;
    press(key.code);
  };
  const onKeyUp = (event: Event): void => {
    release((event as KeyboardEvent).code);
  };

  const onPointerDown = (event: Event): void => {
    const pointer = event as PointerEvent;
    touch = pointer.pointerType === "touch";
    const at = position(pointer);
    let state: PointerState = {
      id: pointer.pointerId,
      x: at.x,
      y: at.y,
      down: true,
      type: pointer.pointerType,
      claimed: false,
    };
    for (const listener of [...downListeners]) {
      if (listener(state) === true) {
        state = { ...state, claimed: true };
        break;
      }
    }
    pointers.set(state.id, state);
    if (!state.claimed) {
      primary = state;
      taps.push({ x: at.x, y: at.y });
      press(POINTER);
    }
    if (target instanceof HTMLElement) {
      try {
        target.setPointerCapture(pointer.pointerId);
      } catch {
        // Synthetic events (tests, scripted players) have no capturable pointer.
      }
    }
    pointerEvents.emit("down", state);
  };
  const onPointerMove = (event: Event): void => {
    const pointer = event as PointerEvent;
    const at = position(pointer);
    const known = pointers.get(pointer.pointerId);
    const state: PointerState = known
      ? { ...known, x: at.x, y: at.y }
      : {
          id: pointer.pointerId,
          x: at.x,
          y: at.y,
          down: false,
          type: pointer.pointerType,
          claimed: false,
        };
    if (known) pointers.set(state.id, state);
    if (!state.claimed && (!primary || primary.id === state.id || !primary.down)) primary = state;
    pointerEvents.emit("move", state);
  };
  const onPointerUp = (event: Event): void => {
    const pointer = event as PointerEvent;
    const known = pointers.get(pointer.pointerId);
    if (!known) return;
    pointers.delete(known.id);
    const at = position(pointer);
    const state: PointerState = { ...known, x: at.x, y: at.y, down: false };
    if (!state.claimed) {
      if (primary?.id === state.id) primary = state;
      const others = [...pointers.values()].some((other) => !other.claimed);
      if (!others) release(POINTER);
    }
    pointerEvents.emit("up", state);
  };

  const releaseAll = (): void => {
    for (const code of [...down]) release(code);
    pointers.clear();
    if (primary) primary = { ...primary, down: false };
  };
  const onBlur = (): void => releaseAll();

  keyTarget.addEventListener("keydown", onKeyDown);
  keyTarget.addEventListener("keyup", onKeyUp);
  target.addEventListener("pointerdown", onPointerDown);
  target.addEventListener("pointermove", onPointerMove);
  target.addEventListener("pointerup", onPointerUp);
  target.addEventListener("pointercancel", onPointerUp);
  window.addEventListener("blur", onBlur);
  if (target instanceof HTMLElement) target.style.touchAction = "none";

  return {
    held: (name) => codesOf(name).some((code) => down.has(code)),
    pressed: (name) => codesOf(name).some((code) => pressedNow.has(code)),
    released: (name) => codesOf(name).some((code) => releasedNow.has(code)),
    get pointer() {
      return primary;
    },
    pointers,
    get taps() {
      return taps;
    },
    get touch() {
      return touch;
    },
    endFrame() {
      pressedNow.clear();
      releasedNow.clear();
      taps = [];
    },
    onFirstGesture(callback) {
      if (gestured) {
        callback();
        return () => undefined;
      }
      gestureCallbacks.add(callback);
      return () => {
        gestureCallbacks.delete(callback);
      };
    },
    onPointerDown(listener) {
      downListeners.add(listener);
      return () => {
        downListeners.delete(listener);
      };
    },
    onPointerMove: (listener) => pointerEvents.on("move", listener),
    onPointerUp: (listener) => pointerEvents.on("up", listener),
    press,
    release,
    releaseAll,
    bind(action, codes) {
      bindings.set(action, codes);
    },
    destroy() {
      keyTarget.removeEventListener("keydown", onKeyDown);
      keyTarget.removeEventListener("keyup", onKeyUp);
      target.removeEventListener("pointerdown", onPointerDown);
      target.removeEventListener("pointermove", onPointerMove);
      target.removeEventListener("pointerup", onPointerUp);
      target.removeEventListener("pointercancel", onPointerUp);
      window.removeEventListener("blur", onBlur);
      for (const type of GESTURES) window.removeEventListener(type, gesture, true);
      pointerEvents.clear();
      downListeners.clear();
    },
  };
}
