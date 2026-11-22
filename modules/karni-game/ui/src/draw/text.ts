import type { Paint } from "./types";

export interface TextStyleOptions {
  /** A CSS font: "16px system-ui, sans-serif". */
  font: string;
  /** Default "#ffffff". null draws no fill. */
  fill?: Paint | null;
  /** An outline drawn under the fill. Default none. */
  stroke?: Paint | null;
  /** Default 2. */
  strokeWidth?: number;
  /** Default "left". */
  align?: CanvasTextAlign;
  /** Default "top", so `y` is the top of the first line. */
  baseline?: CanvasTextBaseline;
  /** Break lines wider than this many game units at spaces. Default no wrap. */
  wrap?: number;
  /** The distance between lines, in game units. Default 1.25 times the font's pixel size. */
  lineHeight?: number;
  /** Laid-out strings kept per style. Default 256. */
  cacheSize?: number;
}

/** A string laid out in one style: measured once, drawn every frame. */
export interface TextLayout {
  readonly lines: readonly string[];
  /** The width of each line, in game units. */
  readonly widths: readonly number[];
  /** The widest line. */
  readonly width: number;
  /** Every line, from the top of the first to the bottom of the last. */
  readonly height: number;
}

/** A text style, made once and used every frame. It keeps the layout of the strings it drew. */
export interface TextStyle {
  readonly font: string;
  readonly fill: Paint | null;
  readonly stroke: Paint | null;
  readonly strokeWidth: number;
  readonly align: CanvasTextAlign;
  readonly baseline: CanvasTextBaseline;
  readonly wrap: number;
  readonly lineHeight: number;
  /** Lay out `text`, or give the layout kept from an earlier call. */
  layout(context: CanvasRenderingContext2D, text: string): TextLayout;
  /** Forget every kept layout: after a web font loads, the widths change. */
  clearCache(): void;
  /** Layouts kept now. */
  readonly cached: number;
}

function fontSize(font: string): number {
  const match = /(\d+(?:\.\d+)?)px/.exec(font);
  return match ? Number(match[1]) : 16;
}

function breakLines(
  context: CanvasRenderingContext2D,
  text: string,
  wrap: number,
): { lines: string[]; widths: number[] } {
  const lines: string[] = [];
  const widths: number[] = [];
  for (const paragraph of text.split("\n")) {
    if (!(wrap > 0)) {
      lines.push(paragraph);
      widths.push(context.measureText(paragraph).width);
      continue;
    }
    let line = "";
    let lineWidth = 0;
    for (const word of paragraph.split(" ")) {
      const next = line === "" ? word : `${line} ${word}`;
      const width = context.measureText(next).width;
      if (width <= wrap || line === "") {
        line = next;
        lineWidth = width;
      } else {
        lines.push(line);
        widths.push(lineWidth);
        line = word;
        lineWidth = context.measureText(word).width;
      }
    }
    lines.push(line);
    widths.push(lineWidth);
  }
  return { lines, widths };
}

/**
 * A text style with a layout cache: the first draw of a string measures it
 * (and wraps it), later draws reuse that, so a HUD redrawn every frame does
 * not measure or split its strings again.
 */
export function textStyle(options: TextStyleOptions): TextStyle {
  const cacheSize = Math.max(1, Math.floor(options.cacheSize ?? 256));
  const cache = new Map<string, TextLayout>();
  const wrap = options.wrap ?? 0;
  const lineHeight = options.lineHeight ?? Math.round(fontSize(options.font) * 1.25);
  const style: TextStyle = {
    font: options.font,
    fill: options.fill === undefined ? "#ffffff" : options.fill,
    stroke: options.stroke ?? null,
    strokeWidth: options.strokeWidth ?? 2,
    align: options.align ?? "left",
    baseline: options.baseline ?? "top",
    wrap,
    lineHeight,
    layout(context, text) {
      const kept = cache.get(text);
      if (kept) return kept;
      context.font = style.font;
      const { lines, widths } = breakLines(context, text, wrap);
      let width = 0;
      for (const w of widths) width = Math.max(width, w);
      const layout: TextLayout = { lines, widths, width, height: lines.length * lineHeight };
      // A simple bound: a style that draws ever-new strings starts over.
      if (cache.size >= cacheSize) cache.clear();
      cache.set(text, layout);
      return layout;
    },
    clearCache() {
      cache.clear();
    },
    get cached() {
      return cache.size;
    },
  };
  return style;
}
