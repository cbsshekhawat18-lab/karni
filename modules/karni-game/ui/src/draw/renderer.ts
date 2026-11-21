import type { Camera } from "./camera";
import { createPainterFrame, type Painter } from "./painter";
import type { DrawView, Paint } from "./types";

/** Draws one part of the frame. `alpha` is the loop's leftover step fraction, `dt` the frame time. */
export type DrawFn = (g: Painter, alpha: number, dt: number) => void;

export interface LayerOptions<L extends string = string> {
  name: L;
  /** Lower draws first. Default: the place in the list. */
  order?: number;
  /** Drawn in game units with no camera: a HUD, a backdrop. Default false. */
  screen?: boolean;
  /**
   * How much the layer moves (and zooms) with the camera: 1 is the world, 0.3
   * a far background, 0 does not move. Default 1.
   */
  parallax?: number;
  /** 0 to 1. Default 1. */
  alpha?: number;
  /** Default true. */
  visible?: boolean;
  /** Skip what is wholly outside the area the layer shows. Default true. */
  cull?: boolean;
}

/** A named group of draw functions, drawn in order with the others. */
export interface Layer {
  readonly name: string;
  order: number;
  screen: boolean;
  parallax: number;
  alpha: number;
  visible: boolean;
  cull: boolean;
  /** Draw `fn` in this layer every frame, after the ones added before it. Returns the remover. */
  add(fn: DrawFn): () => void;
  /** Remove every draw function. */
  clear(): void;
  /** Draw functions in the layer. */
  readonly size: number;
}

export interface RendererOptions<L extends string> {
  /** The canvas, or `context` for a context of your own. */
  canvas?: HTMLCanvasElement;
  context?: CanvasRenderingContext2D;
  /** The view (`createView`): the game's size and how it fits the canvas. */
  view: DrawView;
  /** The camera of every layer that is not a screen layer. Default none (the world is the screen). */
  camera?: Camera | null;
  /** The layers, bottom first: names, or options per layer. */
  layers: readonly (L | LayerOptions<L>)[];
  /** Fills the whole canvas (and the letterbox bars) each frame. null clears it. Default "#000000". */
  background?: Paint | null;
  /** Keep drawing inside the game area, off the letterbox bars. Default true. */
  clip?: boolean;
  /** Smooth scaled images. false keeps pixel art sharp. Default true. */
  smoothing?: boolean;
  /** A draw function that throws. Default `console.error` for the first ten. */
  onError?(error: unknown, layer: L): void;
}

export interface RenderStats {
  /** Shapes, texts and sprites drawn in the last frame. */
  readonly drawn: number;
  /** Ones skipped as off screen. */
  readonly culled: number;
  /** Draw functions called. */
  readonly calls: number;
}

export interface Renderer<L extends string> {
  readonly context: CanvasRenderingContext2D;
  readonly painter: Painter;
  camera: Camera | null;
  layer(name: L): Layer;
  /** Add a draw function to a layer. Returns the remover. */
  on(name: L, fn: DrawFn): () => void;
  /** Draw a frame: every visible layer in order. Call it from the loop's `render`. */
  render(alpha?: number, dt?: number): void;
  readonly stats: RenderStats;
}

/** A class with number fields started as numbers, so a tweened `alpha` is written in place. */
class LayerState implements Layer {
  readonly fns: DrawFn[] = [];
  screen = false;
  parallax = 1;
  alpha = 1;
  visible = true;
  cull = true;
  private place = 0;

  constructor(
    readonly name: string,
    readonly index: number,
    options: LayerOptions,
    private readonly moved: () => void,
  ) {
    this.place = options.order ?? index;
    this.screen = options.screen ?? false;
    this.parallax = options.parallax ?? 1;
    this.alpha = options.alpha ?? 1;
    this.visible = options.visible ?? true;
    this.cull = options.cull ?? true;
  }

  get order(): number {
    return this.place;
  }
  set order(value: number) {
    this.place = value;
    this.moved();
  }
  get size(): number {
    return this.fns.length;
  }

  add(fn: DrawFn): () => void {
    this.fns.push(fn);
    return () => {
      const at = this.fns.indexOf(fn);
      if (at >= 0) this.fns.splice(at, 1);
    };
  }

  clear(): void {
    this.fns.length = 0;
  }
}

/**
 * Layers drawn in order over a view and a camera. Each layer is a list of
 * draw functions in world units (or game units for a screen layer), with
 * its own parallax, opacity and culling. There is no scene graph: a game
 * keeps its own entity list and draws it from a layer's function.
 */
export function createRenderer<L extends string>(options: RendererOptions<L>): Renderer<L> {
  const context = options.context ?? options.canvas?.getContext("2d");
  if (!context) throw new Error("createRenderer: give a canvas with a 2D context, or a context");
  const view = options.view;
  const background = options.background === undefined ? "#000000" : options.background;
  const clip = options.clip ?? true;
  const smoothing = options.smoothing ?? true;
  let reported = 0;
  const onError =
    options.onError ??
    ((error: unknown, layer: L) => {
      if (reported >= 10) return;
      reported += 1;
      console.error(`[karni-game] a draw function of layer "${layer}" threw`, error);
    });
  const { painter, frame } = createPainterFrame(context);
  const stats = { drawn: 0, culled: 0, calls: 0 };
  const layers = new Map<L, LayerState>();
  const ordered: LayerState[] = [];
  let dirty = true;

  options.layers.forEach((spec, index) => {
    const opts: LayerOptions<L> = typeof spec === "string" ? { name: spec } : spec;
    if (layers.has(opts.name))
      throw new Error(`createRenderer: layer "${opts.name}" is named twice`);
    const layer = new LayerState(opts.name, index, opts, () => {
      dirty = true;
    });
    layers.set(opts.name, layer);
    ordered.push(layer);
  });

  const get = (name: L): LayerState => {
    const layer = layers.get(name);
    if (!layer) throw new Error(`createRenderer: no layer "${name}"`);
    return layer;
  };

  const renderer: Renderer<L> = {
    context,
    painter,
    camera: options.camera ?? null,
    layer: get,
    on: (name, fn) => get(name).add(fn),
    render(alpha = 0, dt = 0) {
      if (dirty) {
        ordered.sort((a, b) => a.order - b.order || a.index - b.index);
        dirty = false;
      }
      const canvas = context.canvas;
      context.save();
      context.setTransform(1, 0, 0, 1, 0, 0);
      context.globalAlpha = 1;
      context.globalCompositeOperation = "source-over";
      if (background === null) {
        context.clearRect(0, 0, canvas.width, canvas.height);
      } else {
        context.fillStyle = background;
        context.fillRect(0, 0, canvas.width, canvas.height);
      }
      context.imageSmoothingEnabled = smoothing;
      const k = view.dpr * view.scale;
      const ox = view.dpr * view.offsetX;
      const oy = view.dpr * view.offsetY;
      const w = view.width;
      const h = view.height;
      if (clip) {
        context.setTransform(k, 0, 0, k, ox, oy);
        context.beginPath();
        context.rect(0, 0, w, h);
        context.clip();
      }
      frame.reset();
      let calls = 0;
      const camera = renderer.camera;
      for (let i = 0; i < ordered.length; i += 1) {
        const layer = ordered[i] as LayerState;
        if (!layer.visible || layer.fns.length === 0 || !(layer.alpha > 0)) continue;
        if (layer.screen || !camera) {
          frame.layer(layer.name, k, k, ox, oy, 0, 0, w, h, layer.cull, layer.alpha);
        } else {
          const p = Math.max(0, layer.parallax);
          const zoom = camera.zoom > 0 && Number.isFinite(camera.zoom) ? camera.zoom : 1;
          const z = 1 + (zoom - 1) * p;
          const cx = (camera.x + camera.shakeX) * p + (w / 2) * (1 - p);
          const cy = (camera.y + camera.shakeY) * p + (h / 2) * (1 - p);
          frame.layer(
            layer.name,
            k * z,
            k * z,
            ox + k * (w / 2 - cx * z),
            oy + k * (h / 2 - cy * z),
            cx - w / (2 * z),
            cy - h / (2 * z),
            w / z,
            h / z,
            layer.cull,
            layer.alpha,
          );
        }
        const fns = layer.fns;
        for (let j = 0; j < fns.length; j += 1) {
          if (j > 0) frame.restore();
          calls += 1;
          try {
            (fns[j] as DrawFn)(painter, alpha, dt);
          } catch (error) {
            onError(error, layer.name as L);
          }
        }
      }
      context.restore();
      stats.drawn = painter.drawn;
      stats.culled = painter.culled;
      stats.calls = calls;
    },
    stats,
  };
  return renderer;
}
