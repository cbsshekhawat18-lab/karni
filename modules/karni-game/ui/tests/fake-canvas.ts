/**
 * A 2D context for tests: jsdom has no canvas. `recording` keeps every call
 * with the state it ran in, `silent` does nothing at all (for the test that
 * counts allocations, where recording would allocate).
 */
export interface Call {
  op: string;
  args: readonly unknown[];
  fill: unknown;
  stroke: unknown;
  alpha: number;
  font: string;
  blend: string;
  /** The transform when the call ran: a, b, c, d, e, f. */
  transform: readonly number[];
}

class FakeContext {
  canvas = { width: 960, height: 540 };
  fillStyle: unknown = "#000000";
  strokeStyle: unknown = "#000000";
  globalAlpha = 1;
  globalCompositeOperation = "source-over";
  private currentFont = "10px sans-serif";
  textAlign = "start";
  textBaseline = "alphabetic";
  lineWidth = 1;
  lineJoin = "miter";
  imageSmoothingEnabled = true;
  matrix = [1, 0, 0, 1, 0, 0];

  get font(): string {
    return this.currentFont;
  }
  /** Each font set is logged: browsers parse the font string on every set. */
  set font(value: string) {
    this.currentFont = value;
    this.log("font", [value]);
  }
  stack: unknown[][] = [];

  constructor(readonly calls: Call[] | null) {}

  private log(op: string, args: readonly unknown[]): void {
    this.calls?.push({
      op,
      args: [...args],
      fill: this.fillStyle,
      stroke: this.strokeStyle,
      alpha: this.globalAlpha,
      font: this.font,
      blend: this.globalCompositeOperation,
      transform: [...this.matrix],
    });
  }

  save(): void {
    if (this.calls) {
      this.stack.push([
        this.fillStyle,
        this.strokeStyle,
        this.globalAlpha,
        this.font,
        this.globalCompositeOperation,
        [...this.matrix],
      ]);
    }
    this.log("save", []);
  }
  restore(): void {
    const state = this.stack.pop();
    if (state) {
      [this.fillStyle, this.strokeStyle] = [state[0], state[1]];
      this.globalAlpha = state[2] as number;
      this.currentFont = state[3] as string;
      this.globalCompositeOperation = state[4] as string;
      this.matrix = state[5] as number[];
    }
    this.log("restore", []);
  }
  setTransform(a: number, b: number, c: number, d: number, e: number, f: number): void {
    if (this.calls) this.matrix = [a, b, c, d, e, f];
    this.log("setTransform", [a, b, c, d, e, f]);
  }
  transform(a: number, b: number, c: number, d: number, e: number, f: number): void {
    this.log("transform", [a, b, c, d, e, f]);
  }
  fillRect(x: number, y: number, w: number, h: number): void {
    this.log("fillRect", [x, y, w, h]);
  }
  strokeRect(x: number, y: number, w: number, h: number): void {
    this.log("strokeRect", [x, y, w, h]);
  }
  clearRect(x: number, y: number, w: number, h: number): void {
    this.log("clearRect", [x, y, w, h]);
  }
  beginPath(): void {
    this.log("beginPath", []);
  }
  closePath(): void {
    this.log("closePath", []);
  }
  rect(x: number, y: number, w: number, h: number): void {
    this.log("rect", [x, y, w, h]);
  }
  clip(): void {
    this.log("clip", []);
  }
  arc(x: number, y: number, r: number, a0: number, a1: number): void {
    this.log("arc", [x, y, r, a0, a1]);
  }
  moveTo(x: number, y: number): void {
    this.log("moveTo", [x, y]);
  }
  lineTo(x: number, y: number): void {
    this.log("lineTo", [x, y]);
  }
  fill(): void {
    this.log("fill", []);
  }
  stroke(): void {
    this.log("stroke", []);
  }
  fillText(text: string, x: number, y: number): void {
    this.log("fillText", [text, x, y]);
  }
  strokeText(text: string, x: number, y: number): void {
    this.log("strokeText", [text, x, y]);
  }
  /** Six units a character: enough to test layouts. */
  measureText(text: string): { width: number } {
    this.log("measureText", [text]);
    return { width: text.length * 6 };
  }
  drawImage(...args: unknown[]): void {
    this.log("drawImage", args.slice(1));
  }
}

/** The value, or a failed test when there is none. */
export function must<T>(value: T | undefined | null): T {
  if (value === undefined || value === null) throw new Error("expected a value");
  return value;
}

export function recordingContext(): { context: CanvasRenderingContext2D; calls: Call[] } {
  const calls: Call[] = [];
  const fake = new FakeContext(calls);
  return { context: fake as unknown as CanvasRenderingContext2D, calls };
}

/** Every method a no-op and no argument list built: nothing here allocates. */
class SilentContext {
  canvas = { width: 960, height: 540 };
  fillStyle: unknown = "#000000";
  strokeStyle: unknown = "#000000";
  globalAlpha = 1;
  globalCompositeOperation = "source-over";
  font = "10px sans-serif";
  textAlign = "start";
  textBaseline = "alphabetic";
  lineWidth = 1;
  lineJoin = "miter";
  imageSmoothingEnabled = true;
  private readonly metrics = { width: 0 };
  save(): void {}
  restore(): void {}
  setTransform(): void {}
  transform(): void {}
  fillRect(): void {}
  strokeRect(): void {}
  clearRect(): void {}
  beginPath(): void {}
  closePath(): void {}
  rect(): void {}
  clip(): void {}
  arc(): void {}
  moveTo(): void {}
  lineTo(): void {}
  fill(): void {}
  stroke(): void {}
  fillText(): void {}
  strokeText(): void {}
  measureText(text: string): { width: number } {
    this.metrics.width = text.length * 6;
    return this.metrics;
  }
  drawImage(): void {}
}

export function silentContext(): CanvasRenderingContext2D {
  return new SilentContext() as unknown as CanvasRenderingContext2D;
}

/** The calls of one kind. */
export function ops(calls: readonly Call[], op: string): Call[] {
  return calls.filter((call) => call.op === op);
}

/** A loaded image of a size (a canvas stands in: jsdom loads no images). */
export function fakeImage(width: number, height: number): HTMLCanvasElement {
  return { width, height } as unknown as HTMLCanvasElement;
}

/** A view of a 480 by 270 game, at a scale and pixel ratio. */
export function fakeView(scale = 2, dpr = 1, offsetX = 0, offsetY = 0) {
  return { width: 480, height: 270, dpr, scale, offsetX, offsetY };
}
