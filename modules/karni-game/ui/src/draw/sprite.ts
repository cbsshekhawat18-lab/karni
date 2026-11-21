/** An image a sprite is cut from: a loaded image, a canvas painted in code, a bitmap. */
export type SpriteImage = HTMLImageElement | HTMLCanvasElement | ImageBitmap | OffscreenCanvas;

/** A region of an image, drawn at a size in game units around an anchor. */
export interface Sprite {
  readonly image: SpriteImage;
  /** The region of the image, in image pixels. */
  readonly sx: number;
  readonly sy: number;
  readonly sw: number;
  readonly sh: number;
  /** The drawn size, in game units. */
  readonly w: number;
  readonly h: number;
  /** The anchor, in game units from the region's top-left: the point drawn at x, y. */
  readonly ax: number;
  readonly ay: number;
}

export interface SpriteOptions {
  /** The region, in image pixels. Default the whole image. */
  x?: number;
  y?: number;
  w?: number;
  h?: number;
  /** The anchor as fractions of the size: [0.5, 1] is the bottom centre. Default [0, 0], the top-left. */
  anchor?: readonly [number, number];
  /** Game units per image pixel. Default 1. */
  scale?: number;
}

function imageSize(image: SpriteImage): { width: number; height: number } {
  if ("naturalWidth" in image) return { width: image.naturalWidth, height: image.naturalHeight };
  return { width: image.width, height: image.height };
}

/** A sprite from a whole image or a region of one. */
export function createSprite(image: SpriteImage, options: SpriteOptions = {}): Sprite {
  const size = options.w === undefined || options.h === undefined ? imageSize(image) : null;
  const sw = options.w ?? size?.width ?? 0;
  const sh = options.h ?? size?.height ?? 0;
  const scale = options.scale ?? 1;
  const [ax, ay] = options.anchor ?? [0, 0];
  return {
    image,
    sx: options.x ?? 0,
    sy: options.y ?? 0,
    sw,
    sh,
    w: sw * scale,
    h: sh * scale,
    ax: ax * sw * scale,
    ay: ay * sh * scale,
  };
}

export interface SheetOptions {
  /** How many frames to cut. Default every whole cell. */
  count?: number;
  /** Pixels around the whole grid. Default 0. */
  margin?: number;
  /** Pixels between cells. Default 0. */
  spacing?: number;
  /** Cells per row. Default as many as fit the image's width. */
  columns?: number;
  anchor?: readonly [number, number];
  scale?: number;
}

/** The frames of a sprite sheet laid out in a grid, left to right and top to bottom. */
export function sheetFrames(
  image: SpriteImage,
  frameWidth: number,
  frameHeight: number,
  options: SheetOptions = {},
): Sprite[] {
  const margin = options.margin ?? 0;
  const spacing = options.spacing ?? 0;
  const size = imageSize(image);
  const columns =
    options.columns ??
    Math.max(1, Math.floor((size.width - margin * 2 + spacing) / (frameWidth + spacing)));
  const rows = Math.max(
    1,
    Math.floor((size.height - margin * 2 + spacing) / (frameHeight + spacing)),
  );
  const count = options.count ?? columns * rows;
  const frames: Sprite[] = [];
  for (let i = 0; i < count; i += 1) {
    const column = i % columns;
    const row = Math.floor(i / columns);
    frames.push(
      createSprite(image, {
        x: margin + column * (frameWidth + spacing),
        y: margin + row * (frameHeight + spacing),
        w: frameWidth,
        h: frameHeight,
        anchor: options.anchor,
        scale: options.scale,
      }),
    );
  }
  return frames;
}

/** A named run of frames played at a rate. */
export interface Clip {
  readonly frames: readonly Sprite[];
  /** Frames per second. */
  readonly fps: number;
  readonly loop: boolean;
}

export interface ClipOptions {
  /** Frame numbers in the sheet, or a range (both ends included). */
  frames: readonly number[] | { from: number; to: number };
  /** Default 10. */
  fps?: number;
  /** Default true. A clip that does not loop stops on its last frame. */
  loop?: boolean;
}

/** Name runs of a sheet's frames: `{ run: { frames: { from: 2, to: 7 }, fps: 12 } }`. */
export function defineClips<K extends string>(
  frames: readonly Sprite[],
  clips: Record<K, ClipOptions>,
): Record<K, Clip> {
  const out = {} as Record<K, Clip>;
  for (const name of Object.keys(clips) as K[]) {
    const spec = clips[name];
    const numbers: number[] = [];
    if ("from" in spec.frames) {
      const { from, to } = spec.frames;
      const step = to >= from ? 1 : -1;
      for (let n = from; step > 0 ? n <= to : n >= to; n += step) numbers.push(n);
    } else {
      numbers.push(...spec.frames);
    }
    const picked = numbers.map((n) => {
      const frame = frames[n];
      if (!frame)
        throw new Error(
          `defineClips: clip "${name}" names frame ${n}, the sheet has ${frames.length}`,
        );
      return frame;
    });
    if (picked.length === 0) throw new Error(`defineClips: clip "${name}" has no frames`);
    out[name] = { frames: picked, fps: spec.fps ?? 10, loop: spec.loop ?? true };
  }
  return out;
}

/** Plays one clip at a time for one thing on screen. */
export interface Animator<K extends string> {
  /** Switch clip. The same clip keeps playing unless `restart` is true. */
  play(name: K, restart?: boolean): void;
  /** Advance by `dt` seconds. */
  update(dt: number): void;
  /** The frame to draw now. */
  readonly sprite: Sprite;
  readonly clip: K;
  /** The frame's place in the clip. */
  readonly index: number;
  /** A clip that does not loop has shown its last frame. */
  readonly done: boolean;
  /** Playback rate: 2 is twice as fast. Default 1. */
  speed: number;
}

export function createAnimator<K extends string>(
  clips: Record<K, Clip>,
  first: K,
  onEnd?: (clip: K) => void,
): Animator<K> {
  let name = first;
  let clip = clips[first];
  let time = 0;
  let index = 0;
  let done = false;
  const animator: Animator<K> = {
    play(next, restart = false) {
      if (next === name && !restart) return;
      name = next;
      clip = clips[next];
      time = 0;
      index = 0;
      done = false;
    },
    update(dt) {
      if (done || !(dt > 0) || clip.fps <= 0) return;
      time += dt * animator.speed;
      const frame = Math.floor(time * clip.fps);
      const count = clip.frames.length;
      if (frame < count) {
        index = frame;
      } else if (clip.loop) {
        index = frame % count;
        time %= count / clip.fps;
      } else {
        index = count - 1;
        done = true;
        onEnd?.(name);
      }
    },
    get sprite() {
      return clip.frames[index] as Sprite;
    },
    get clip() {
      return name;
    },
    get index() {
      return index;
    },
    get done() {
      return done;
    },
    speed: 1,
  };
  return animator;
}
