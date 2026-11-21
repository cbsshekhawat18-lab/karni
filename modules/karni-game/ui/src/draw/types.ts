/** A fill or stroke: a CSS colour, a gradient or a pattern. */
export type Paint = string | CanvasGradient | CanvasPattern;

/**
 * What drawing needs of the view: its size in game units and how game units
 * map to the canvas. `createView` gives all of it.
 */
export interface DrawView {
  /** The size the game draws in, in game units. */
  readonly width: number;
  readonly height: number;
  /** Device pixels per CSS pixel. */
  readonly dpr: number;
  /** CSS pixels per game unit. */
  readonly scale: number;
  /** Where the game area starts on the canvas, in CSS pixels. */
  readonly offsetX: number;
  readonly offsetY: number;
}

/** A point in game or world units. */
export interface Point {
  x: number;
  y: number;
}
