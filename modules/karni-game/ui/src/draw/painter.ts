import type { Sprite } from "./sprite";
import type { TextLayout, TextStyle } from "./text";
import type { Paint } from "./types";

const TAU = Math.PI * 2;

/**
 * Shape, text and sprite helpers over a 2D context, in the units of the
 * layer being drawn (world units on a camera layer, game units on a screen
 * layer). Inside a renderer, anything wholly off screen is skipped (culled)
 * before it reaches the canvas.
 */
export interface Painter {
  /**
   * The raw context, set to the layer's units: the escape hatch for anything
   * the helpers do not cover. Reading it makes the next `text` set its font again.
   */
  readonly ctx: CanvasRenderingContext2D;
  /** The layer being drawn, or null outside a renderer. */
  readonly layer: string | null;
  /** The area this layer shows, in its own units (for culling of your own). */
  readonly left: number;
  readonly top: number;
  readonly width: number;
  readonly height: number;
  /** True when a box is at least partly in the area this layer shows. */
  visible(x: number, y: number, w: number, h: number): boolean;
  /** Opacity of what is drawn next, 0 to 1, on top of the layer's own. Reset for each draw function. */
  alpha: number;
  rect(x: number, y: number, w: number, h: number, fill: Paint): void;
  strokeRect(x: number, y: number, w: number, h: number, stroke: Paint, lineWidth?: number): void;
  circle(x: number, y: number, r: number, fill: Paint): void;
  strokeCircle(x: number, y: number, r: number, stroke: Paint, lineWidth?: number): void;
  line(x1: number, y1: number, x2: number, y2: number, stroke: Paint, lineWidth?: number): void;
  /** A closed polygon from flat coordinates: [x0, y0, x1, y1, ...]. */
  poly(
    points: readonly number[],
    fill: Paint | null,
    stroke?: Paint | null,
    lineWidth?: number,
  ): void;
  /** Text in a style made once with `textStyle`. Lines break at "\n" and at the style's `wrap`. */
  text(text: string, x: number, y: number, style: TextStyle): void;
  /** The layout of `text` in `style` (its lines and size), measured once and kept. */
  measure(text: string, style: TextStyle): TextLayout;
  /**
   * A sprite with its anchor at x, y. A negative scale flips it, `rotation`
   * is in radians. False when it was culled or its image is not loaded yet.
   */
  sprite(
    sprite: Sprite,
    x: number,
    y: number,
    scaleX?: number,
    scaleY?: number,
    rotation?: number,
  ): boolean;
  /** Things drawn and culled since the frame began. */
  readonly drawn: number;
  readonly culled: number;
}

/** What the renderer sets on its painter for each layer. */
export interface PainterFrame {
  /** A new frame: counters to zero, the font state forgotten. */
  reset(): void;
  /** The layer's transform (no rotation) and its area, or culling off with `cull` false. */
  layer(
    name: string,
    a: number,
    d: number,
    e: number,
    f: number,
    left: number,
    top: number,
    width: number,
    height: number,
    cull: boolean,
    alpha: number,
  ): void;
  /** Back to the layer's transform and opacity, before each draw function. */
  restore(): void;
}

function loaded(sprite: Sprite): boolean {
  const image = sprite.image;
  if ("complete" in image) return image.complete && image.naturalWidth > 0;
  return image.width > 0;
}

/** A painter and the handle a renderer drives it with. */
export function createPainterFrame(context: CanvasRenderingContext2D): {
  painter: Painter;
  frame: PainterFrame;
} {
  let name: string | null = null;
  let known = false;
  let ba = 1;
  let bd = 1;
  let be = 0;
  let bf = 0;
  let left = -Infinity;
  let top = -Infinity;
  let width = Infinity;
  let height = Infinity;
  let culling = false;
  let layerAlpha = 1;
  let alpha = 1;
  let lastStyle: TextStyle | null = null;
  let drawn = 0;
  let culled = 0;

  const sees = (x: number, y: number, w: number, h: number): boolean =>
    !culling || (x + w >= left && x <= left + width && y + h >= top && y <= top + height);
  /** Count and test: true when the shape should be drawn. */
  const keep = (x: number, y: number, w: number, h: number): boolean => {
    if (sees(x, y, w, h)) {
      drawn += 1;
      return true;
    }
    culled += 1;
    return false;
  };

  const setStyle = (style: TextStyle): void => {
    if (style === lastStyle) return;
    context.font = style.font;
    context.textAlign = style.align;
    context.textBaseline = style.baseline;
    lastStyle = style;
  };
  const drawLine = (text: string, x: number, y: number, style: TextStyle): void => {
    if (style.stroke !== null) {
      context.strokeStyle = style.stroke;
      context.lineWidth = style.strokeWidth;
      context.lineJoin = "round";
      context.strokeText(text, x, y);
    }
    if (style.fill !== null) {
      context.fillStyle = style.fill;
      context.fillText(text, x, y);
    }
  };

  const painter: Painter = {
    get ctx() {
      lastStyle = null;
      return context;
    },
    get layer() {
      return name;
    },
    get left() {
      return left;
    },
    get top() {
      return top;
    },
    get width() {
      return width;
    },
    get height() {
      return height;
    },
    visible: sees,
    get alpha() {
      return alpha;
    },
    set alpha(value: number) {
      alpha = Math.max(0, Math.min(1, Number.isFinite(value) ? value : 1));
      context.globalAlpha = layerAlpha * alpha;
    },
    rect(x, y, w, h, fill) {
      if (!keep(x, y, w, h)) return;
      context.fillStyle = fill;
      context.fillRect(x, y, w, h);
    },
    strokeRect(x, y, w, h, stroke, lineWidth = 1) {
      const pad = lineWidth / 2;
      if (!keep(x - pad, y - pad, w + lineWidth, h + lineWidth)) return;
      context.strokeStyle = stroke;
      context.lineWidth = lineWidth;
      context.strokeRect(x, y, w, h);
    },
    circle(x, y, r, fill) {
      if (!keep(x - r, y - r, r * 2, r * 2)) return;
      context.fillStyle = fill;
      context.beginPath();
      context.arc(x, y, r, 0, TAU);
      context.fill();
    },
    strokeCircle(x, y, r, stroke, lineWidth = 1) {
      const outer = r + lineWidth / 2;
      if (!keep(x - outer, y - outer, outer * 2, outer * 2)) return;
      context.strokeStyle = stroke;
      context.lineWidth = lineWidth;
      context.beginPath();
      context.arc(x, y, r, 0, TAU);
      context.stroke();
    },
    line(x1, y1, x2, y2, stroke, lineWidth = 1) {
      const pad = lineWidth / 2;
      const x = Math.min(x1, x2) - pad;
      const y = Math.min(y1, y2) - pad;
      if (!keep(x, y, Math.abs(x2 - x1) + lineWidth, Math.abs(y2 - y1) + lineWidth)) return;
      context.strokeStyle = stroke;
      context.lineWidth = lineWidth;
      context.beginPath();
      context.moveTo(x1, y1);
      context.lineTo(x2, y2);
      context.stroke();
    },
    poly(points, fill, stroke = null, lineWidth = 1) {
      if (points.length < 6) return;
      let minX = Infinity;
      let minY = Infinity;
      let maxX = -Infinity;
      let maxY = -Infinity;
      for (let i = 0; i + 1 < points.length; i += 2) {
        const px = points[i] as number;
        const py = points[i + 1] as number;
        if (px < minX) minX = px;
        if (px > maxX) maxX = px;
        if (py < minY) minY = py;
        if (py > maxY) maxY = py;
      }
      const pad = stroke === null ? 0 : lineWidth / 2;
      if (!keep(minX - pad, minY - pad, maxX - minX + pad * 2, maxY - minY + pad * 2)) return;
      context.beginPath();
      context.moveTo(points[0] as number, points[1] as number);
      for (let i = 2; i + 1 < points.length; i += 2) {
        context.lineTo(points[i] as number, points[i + 1] as number);
      }
      context.closePath();
      if (fill !== null) {
        context.fillStyle = fill;
        context.fill();
      }
      if (stroke !== null) {
        context.strokeStyle = stroke;
        context.lineWidth = lineWidth;
        context.stroke();
      }
    },
    text(text, x, y, style) {
      setStyle(style);
      if (!culling && style.wrap <= 0 && text.indexOf("\n") < 0) {
        drawn += 1;
        drawLine(text, x, y, style);
        return;
      }
      const layout = style.layout(context, text);
      const align = style.align;
      const boxX =
        align === "center"
          ? x - layout.width / 2
          : align === "right" || align === "end"
            ? x - layout.width
            : x;
      const base = style.baseline;
      const boxY =
        base === "top" || base === "hanging"
          ? y
          : base === "middle"
            ? y - style.lineHeight / 2
            : y - style.lineHeight;
      const pad = style.stroke === null ? 0 : style.strokeWidth;
      if (!keep(boxX - pad, boxY - pad, layout.width + pad * 2, layout.height + pad * 2)) return;
      const lines = layout.lines;
      for (let i = 0; i < lines.length; i += 1) {
        drawLine(lines[i] as string, x, y + i * style.lineHeight, style);
      }
    },
    measure(text, style) {
      const layout = style.layout(context, text);
      // layout() sets the font: the next text() must set its whole style again.
      lastStyle = null;
      return layout;
    },
    sprite(sprite, x, y, scaleX = 1, scaleY = 1, rotation = 0) {
      if (!loaded(sprite)) return false;
      const image = sprite.image;
      if (rotation === 0 && scaleX === 1 && scaleY === 1) {
        const dx = x - sprite.ax;
        const dy = y - sprite.ay;
        if (!keep(dx, dy, sprite.w, sprite.h)) return false;
        context.drawImage(
          image,
          sprite.sx,
          sprite.sy,
          sprite.sw,
          sprite.sh,
          dx,
          dy,
          sprite.w,
          sprite.h,
        );
        return true;
      }
      // Rotated or scaled: cull on a box that holds every turn of it.
      const reach =
        Math.max(Math.abs(scaleX), Math.abs(scaleY)) *
        Math.hypot(
          Math.max(sprite.ax, sprite.w - sprite.ax),
          Math.max(sprite.ay, sprite.h - sprite.ay),
        );
      if (!keep(x - reach, y - reach, reach * 2, reach * 2)) return false;
      const cos = Math.cos(rotation);
      const sin = Math.sin(rotation);
      if (known) {
        context.setTransform(
          ba * cos * scaleX,
          bd * sin * scaleX,
          -ba * sin * scaleY,
          bd * cos * scaleY,
          ba * x + be,
          bd * y + bf,
        );
        context.drawImage(
          image,
          sprite.sx,
          sprite.sy,
          sprite.sw,
          sprite.sh,
          -sprite.ax,
          -sprite.ay,
          sprite.w,
          sprite.h,
        );
        context.setTransform(ba, 0, 0, bd, be, bf);
      } else {
        context.save();
        context.transform(cos * scaleX, sin * scaleX, -sin * scaleY, cos * scaleY, x, y);
        context.drawImage(
          image,
          sprite.sx,
          sprite.sy,
          sprite.sw,
          sprite.sh,
          -sprite.ax,
          -sprite.ay,
          sprite.w,
          sprite.h,
        );
        context.restore();
      }
      return true;
    },
    get drawn() {
      return drawn;
    },
    get culled() {
      return culled;
    },
  };

  const frame: PainterFrame = {
    reset() {
      drawn = 0;
      culled = 0;
      lastStyle = null;
    },
    layer(layerName, a, d, e, f, l, t, w, h, cull, opacity) {
      name = layerName;
      known = true;
      ba = a;
      bd = d;
      be = e;
      bf = f;
      left = l;
      top = t;
      width = w;
      height = h;
      culling = cull;
      layerAlpha = opacity;
      frame.restore();
    },
    restore() {
      context.setTransform(ba, 0, 0, bd, be, bf);
      alpha = 1;
      context.globalAlpha = layerAlpha;
    },
  };
  return { painter, frame };
}

/**
 * A painter over a context of your own, with no renderer: the helpers draw
 * with whatever transform the context has, and nothing is culled.
 */
export function createPainter(context: CanvasRenderingContext2D): Painter {
  return createPainterFrame(context).painter;
}
