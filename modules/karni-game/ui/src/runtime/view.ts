import { createEmitter } from "../internal/emitter";

export type Fit =
  /** The whole virtual area shows, centred, with bars on the long side. */
  | "letterbox"
  /** The virtual area fills the canvas, cut off on the long side. */
  | "cover";

export interface ViewOptions {
  canvas: HTMLCanvasElement;
  /**
   * The virtual resolution the game draws in. Omit both for native mode: one
   * unit is one CSS pixel and the game sees the canvas's own size.
   */
  width?: number;
  height?: number;
  /** How the virtual area fits the canvas. Default "letterbox". */
  fit?: Fit;
  /** The highest device pixel ratio used on a mouse device. Default 2. */
  maxDpr?: number;
  /** The highest device pixel ratio used on a touch device (to spare phone GPUs). Default 1.5. */
  touchMaxDpr?: number;
  /**
   * What the canvas fills: an element (its box is measured) or the window
   * (default: the canvas's parent element, or the window when it has none).
   */
  container?: HTMLElement | Window;
  /** Set the canvas's CSS size to the container's. Default true. */
  sizeCanvas?: boolean;
  /** The device pixel ratio. Default `window.devicePixelRatio`. */
  devicePixelRatio?: () => number;
  /** Whether this is a touch device. Default: a coarse pointer or touch points. */
  isTouch?: () => boolean;
}

export interface ViewState {
  /** The canvas's CSS size. */
  readonly cssWidth: number;
  readonly cssHeight: number;
  /** The canvas's backing store, in device pixels. */
  readonly pixelWidth: number;
  readonly pixelHeight: number;
  /** The device pixel ratio in use, after the cap. */
  readonly dpr: number;
  /** The size the game draws in: the virtual resolution, or the CSS size in native mode. */
  readonly width: number;
  readonly height: number;
  /** CSS pixels per game unit. */
  readonly scale: number;
  /** Where the game area starts on the canvas, in CSS pixels (the letterbox bar). */
  readonly offsetX: number;
  readonly offsetY: number;
}

export interface View extends ViewState {
  /** A pointer's client position (from a pointer event) in game units. */
  toGame(clientX: number, clientY: number): { x: number; y: number };
  /** Set the 2D context's transform so drawing uses game units. */
  apply(context: CanvasRenderingContext2D): void;
  /** Measure again. It runs on resize, rotation and viewport changes by itself. */
  resize(): void;
  onResize(listener: (view: ViewState) => void): () => void;
  /** Remove every listener. */
  destroy(): void;
}

function defaultTouch(): boolean {
  if (typeof window === "undefined") return false;
  const coarse =
    typeof window.matchMedia === "function" && window.matchMedia("(pointer: coarse)").matches;
  return coarse || (typeof navigator !== "undefined" && navigator.maxTouchPoints > 0);
}

/** The CSS size of what the canvas fills. */
function measure(container: HTMLElement | Window): { width: number; height: number } {
  if ("innerWidth" in container) {
    const visual = container.visualViewport;
    return {
      width: visual?.width ?? container.innerWidth,
      height: visual?.height ?? container.innerHeight,
    };
  }
  const box = container.getBoundingClientRect();
  return { width: box.width, height: box.height };
}

/**
 * Size a canvas for sharp drawing on any screen: the backing store follows
 * the CSS size times the device pixel ratio, capped lower on touch devices,
 * and an optional virtual resolution is fitted inside with letterboxing.
 */
export function createView(options: ViewOptions): View {
  const { canvas } = options;
  const virtual = options.width && options.height ? { w: options.width, h: options.height } : null;
  const fit = options.fit ?? "letterbox";
  const container: HTMLElement | Window = options.container ?? canvas.parentElement ?? window;
  const sizeCanvas = options.sizeCanvas ?? true;
  const ratio = options.devicePixelRatio ?? (() => window.devicePixelRatio || 1);
  const isTouch = options.isTouch ?? defaultTouch;
  const events = createEmitter<{ resize: ViewState }>();

  const state = {
    cssWidth: 0,
    cssHeight: 0,
    pixelWidth: 0,
    pixelHeight: 0,
    dpr: 1,
    width: 0,
    height: 0,
    scale: 1,
    offsetX: 0,
    offsetY: 0,
  };

  const resize = (): void => {
    const size = measure(container);
    const cssWidth = Math.max(1, Math.floor(size.width));
    const cssHeight = Math.max(1, Math.floor(size.height));
    const cap = isTouch() ? (options.touchMaxDpr ?? 1.5) : (options.maxDpr ?? 2);
    const dpr = Math.max(0.5, Math.min(ratio(), cap));
    const pixelWidth = Math.round(cssWidth * dpr);
    const pixelHeight = Math.round(cssHeight * dpr);
    if (sizeCanvas) {
      canvas.style.width = `${cssWidth}px`;
      canvas.style.height = `${cssHeight}px`;
    }
    if (canvas.width !== pixelWidth) canvas.width = pixelWidth;
    if (canvas.height !== pixelHeight) canvas.height = pixelHeight;
    let scale = 1;
    let width = cssWidth;
    let height = cssHeight;
    if (virtual) {
      const sx = cssWidth / virtual.w;
      const sy = cssHeight / virtual.h;
      scale = fit === "cover" ? Math.max(sx, sy) : Math.min(sx, sy);
      width = virtual.w;
      height = virtual.h;
    }
    Object.assign(state, {
      cssWidth,
      cssHeight,
      pixelWidth,
      pixelHeight,
      dpr,
      width,
      height,
      scale,
      offsetX: (cssWidth - width * scale) / 2,
      offsetY: (cssHeight - height * scale) / 2,
    });
    events.emit("resize", { ...state });
  };

  const onWindow = (): void => resize();
  window.addEventListener("resize", onWindow);
  window.addEventListener("orientationchange", onWindow);
  window.visualViewport?.addEventListener("resize", onWindow);
  let observer: ResizeObserver | null = null;
  if (!("innerWidth" in container) && typeof ResizeObserver === "function") {
    observer = new ResizeObserver(onWindow);
    observer.observe(container);
  }
  resize();

  const view: View = {
    get cssWidth() {
      return state.cssWidth;
    },
    get cssHeight() {
      return state.cssHeight;
    },
    get pixelWidth() {
      return state.pixelWidth;
    },
    get pixelHeight() {
      return state.pixelHeight;
    },
    get dpr() {
      return state.dpr;
    },
    get width() {
      return state.width;
    },
    get height() {
      return state.height;
    },
    get scale() {
      return state.scale;
    },
    get offsetX() {
      return state.offsetX;
    },
    get offsetY() {
      return state.offsetY;
    },
    toGame(clientX, clientY) {
      const box = canvas.getBoundingClientRect();
      return {
        x: (clientX - box.left - state.offsetX) / state.scale,
        y: (clientY - box.top - state.offsetY) / state.scale,
      };
    },
    apply(context) {
      const k = state.dpr * state.scale;
      context.setTransform(k, 0, 0, k, state.dpr * state.offsetX, state.dpr * state.offsetY);
    },
    resize,
    onResize: (listener) => events.on("resize", listener),
    destroy() {
      window.removeEventListener("resize", onWindow);
      window.removeEventListener("orientationchange", onWindow);
      window.visualViewport?.removeEventListener("resize", onWindow);
      observer?.disconnect();
      events.clear();
    },
  };
  return view;
}
