import { createEmitter } from "../internal/emitter";
import type { GameAudio } from "../audio/audio";
import type { GameClient } from "../client/client";
import type { Input } from "../input/input";
import type { Portal } from "../portal/types";
import type { Loop } from "../runtime/loop";
import type { Save } from "../save/save";

/**
 * The services a scene is given. Each is optional here so a test can supply
 * only what a scene uses. A game extends it with its own (a canvas context,
 * its rules, its settings) and passes the type to `createSceneStack`, so no
 * scene imports a global.
 */
export interface SceneServices {
  loop?: Loop;
  input?: Input;
  audio?: GameAudio;
  save?: Save<unknown>;
  portal?: Portal;
  client?: GameClient;
}

/** What every hook of a scene receives. */
export interface SceneContext<S extends object = SceneServices, D = unknown> {
  readonly services: S;
  readonly stack: SceneStack<S>;
  /** The `data` it was pushed or replaced with. */
  readonly data: D;
}

/**
 * One screen of a game: a title, a level, a pause menu. Every hook is
 * optional. Make scenes with a function (`createPlayScene()`) so each push
 * gets its own state.
 */
export interface Scene<S extends object = SceneServices, D = unknown> {
  /** A name for `stack.has(name)` and for logs. */
  name?: string;
  /**
   * An overlay is drawn on top of the scene below it instead of replacing it.
   * It is the default of a scene pushed with `overlay: true`.
   */
  overlay?: boolean;
  /** The scene became the top of the stack. */
  enter?(context: SceneContext<S, D>): void;
  /** The scene left the stack. */
  exit?(context: SceneContext<S, D>): void;
  /** Another scene covers this one or paused it (an overlay was pushed). */
  pause?(context: SceneContext<S, D>): void;
  /** The scene above this one left: it runs again. */
  resume?(context: SceneContext<S, D>): void;
  /** Advance by `dt` seconds. With the loop's fixed step this is the step. */
  update?(context: SceneContext<S, D>, dt: number): void;
  /** Draw. `alpha` is the leftover fraction of a fixed step. Scenes below an overlay draw first. */
  draw?(context: SceneContext<S, D>, alpha: number): void;
}

export interface TransitionOptions {
  /**
   * Seconds the change takes: half to fade out, half to fade in, with the
   * swap in the middle. Omit or 0 for an instant change. It is 0 when the
   * player prefers reduced motion.
   */
  duration?: number;
}

export interface PushOptions<D = unknown> extends TransitionOptions {
  /** Draw it over the scene below instead of replacing it. Default: the scene's own `overlay`. */
  overlay?: boolean;
  /**
   * An overlay stops the scenes below from updating (they are still drawn).
   * Set false for an overlay that is only a layer, such as a HUD. Default true.
   */
  pauses?: boolean;
  data?: D;
}

export interface ReplaceOptions<D = unknown> extends TransitionOptions {
  data?: D;
}

export interface SceneStackEvents {
  /** The top scene changed (a push, pop or replace took effect). */
  change: { top: string | undefined; depth: number };
}

export interface SceneStackOptions<S extends object = SceneServices> {
  services: S;
  /**
   * Is the player asking for less motion? When true every transition is
   * instant. Default: the browser's `prefers-reduced-motion`. A game with a
   * setting passes `() => settings.reducedMotion`.
   */
  reducedMotion?: () => boolean;
  /** A hook that threw. The stack keeps going. Default: `console.error`. */
  onError?(error: unknown, hook: string, scene: Scene<S, never>): void;
}

export interface SceneStack<S extends object = SceneServices> {
  readonly services: S;
  /** The scene on top, or null when the stack is empty. */
  readonly top: Scene<S, never> | null;
  /** The number of scenes. */
  readonly depth: number;
  /** The names of the scenes, bottom first. */
  readonly names: readonly (string | undefined)[];
  has(name: string): boolean;
  /**
   * Put a scene on top. A full scene replaces the one below on screen. An
   * overlay is drawn over it and, by default, pauses it.
   */
  push<D = unknown>(scene: Scene<S, D>, options?: PushOptions<D>): void;
  /** Remove the top scene. */
  pop(options?: TransitionOptions): void;
  /** Swap the top scene for another. */
  replace<D = unknown>(scene: Scene<S, D>, options?: ReplaceOptions<D>): void;
  /** Remove every scene, top first. */
  clear(): void;
  /**
   * A change is waiting or fading. Changes asked for meanwhile (also from
   * inside a hook) wait their turn and run in order.
   */
  readonly transitioning: boolean;
  /**
   * How covered the screen is while a transition runs: 0 to 1, up on the way
   * out and down on the way in. Draw it over everything with `drawCover`.
   */
  readonly cover: number;
  /** Advance the scenes that are running, and any transition. Call it from the loop's update. */
  update(dt: number): void;
  /** Draw the scenes that are showing, bottom first. Call it from the loop's render. */
  draw(alpha?: number): void;
  on<K extends keyof SceneStackEvents>(
    event: K,
    listener: (value: SceneStackEvents[K]) => void,
  ): () => void;
}

interface Entry<S extends object> {
  scene: Scene<S, never>;
  context: SceneContext<S, never>;
  overlay: boolean;
  pauses: boolean;
}

type Op<S extends object> =
  | { kind: "push"; entry: Entry<S>; duration: number }
  | { kind: "pop"; duration: number }
  | { kind: "replace"; entry: Entry<S>; duration: number }
  | { kind: "clear"; duration: number };

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/**
 * A stack of scenes with overlays and fade transitions. Scenes get their
 * services from the stack, never from imports. A change asked for inside a
 * hook is applied after the update that asked for it.
 */
export function createSceneStack<S extends object = SceneServices>(
  options: SceneStackOptions<S>,
): SceneStack<S> {
  const reduced = options.reducedMotion ?? prefersReducedMotion;
  const report =
    options.onError ??
    ((error: unknown, hook: string, scene: Scene<S, never>) => {
      console.error(`[karni-game] the ${hook} of scene "${scene.name ?? "?"}" threw`, error);
    });
  const events = createEmitter<SceneStackEvents>();
  const entries: Entry<S>[] = [];
  const queue: Op<S>[] = [];
  let busy = false;
  let fade: { phase: "out" | "in"; time: number; half: number; op: Op<S> | null } | null = null;

  const call = (
    entry: Entry<S>,
    hook: "enter" | "exit" | "pause" | "resume" | "update" | "draw",
    ...args: [number?]
  ): void => {
    const method = entry.scene[hook] as
      ((context: SceneContext<S, never>, value?: number) => void) | undefined;
    if (!method) return;
    try {
      method.call(entry.scene, entry.context, args[0]);
    } catch (error) {
      report(error, hook, entry.scene);
    }
  };

  const announce = (): void => {
    events.emit("change", { top: entries[entries.length - 1]?.scene.name, depth: entries.length });
  };

  const perform = (op: Op<S>): void => {
    const below = entries[entries.length - 1];
    switch (op.kind) {
      case "push":
        if (below) call(below, "pause");
        entries.push(op.entry);
        call(op.entry, "enter");
        break;
      case "pop": {
        const gone = entries.pop();
        if (gone) call(gone, "exit");
        const now = entries[entries.length - 1];
        if (now) call(now, "resume");
        break;
      }
      case "replace": {
        const gone = entries.pop();
        if (gone) call(gone, "exit");
        entries.push(op.entry);
        call(op.entry, "enter");
        break;
      }
      case "clear":
        for (let top = entries.pop(); top; top = entries.pop()) call(top, "exit");
        break;
    }
    announce();
  };

  const run = (): void => {
    while (!busy && !fade && queue.length > 0) {
      const op = queue.shift();
      if (!op) break;
      if (op.duration > 0 && !reduced() && entries.length > 0) {
        fade = { phase: "out", time: 0, half: op.duration / 2, op };
      } else {
        busy = true;
        try {
          perform(op);
        } finally {
          busy = false;
        }
      }
    }
  };

  const ask = (op: Op<S>): void => {
    queue.push(op);
    run();
  };

  const entryFor = <D>(
    scene: Scene<S, D>,
    overlay: boolean,
    pauses: boolean,
    data: D | undefined,
  ): Entry<S> => {
    const entry: Entry<S> = {
      scene: scene as unknown as Scene<S, never>,
      overlay,
      pauses,
      context: {
        services: options.services,
        stack,
        data: data as never,
      },
    };
    return entry;
  };

  /** The scenes that update: the top one, and those below it that overlays do not pause. */
  const running = (): Entry<S>[] => {
    let from = entries.length - 1;
    while (from > 0 && entries[from]?.overlay && entries[from]?.pauses === false) from -= 1;
    return entries.slice(Math.max(0, from));
  };
  /** The scenes that show: the top one, and those below it that an overlay lets through. */
  const showing = (): Entry<S>[] => {
    let from = entries.length - 1;
    while (from > 0 && entries[from]?.overlay) from -= 1;
    return entries.slice(Math.max(0, from));
  };

  const stack: SceneStack<S> = {
    services: options.services,
    get top() {
      return entries[entries.length - 1]?.scene ?? null;
    },
    get depth() {
      return entries.length;
    },
    get names() {
      return entries.map((entry) => entry.scene.name);
    },
    has: (name) => entries.some((entry) => entry.scene.name === name),
    push(scene, pushOptions = {}) {
      const overlay = pushOptions.overlay ?? scene.overlay ?? false;
      ask({
        kind: "push",
        entry: entryFor(scene, overlay, pushOptions.pauses ?? true, pushOptions.data),
        duration: pushOptions.duration ?? 0,
      });
    },
    pop: (popOptions = {}) => ask({ kind: "pop", duration: popOptions.duration ?? 0 }),
    replace(scene, replaceOptions = {}) {
      ask({
        kind: "replace",
        entry: entryFor(scene, scene.overlay ?? false, true, replaceOptions.data),
        duration: replaceOptions.duration ?? 0,
      });
    },
    clear: () => ask({ kind: "clear", duration: 0 }),
    get transitioning() {
      return fade !== null || queue.length > 0;
    },
    get cover() {
      if (!fade) return 0;
      const progress = Math.min(1, fade.time / fade.half);
      return fade.phase === "out" ? progress : 1 - progress;
    },
    update(dt) {
      if (fade) {
        fade.time += dt;
        if (fade.time >= fade.half) {
          if (fade.phase === "out" && fade.op) {
            const op = fade.op;
            fade = { phase: "in", time: 0, half: fade.half, op: null };
            busy = true;
            try {
              perform(op);
            } finally {
              busy = false;
            }
          } else {
            fade = null;
          }
        }
      }
      // Scenes stand still while the screen fades out, and run again as it fades in.
      if (fade?.phase !== "out") {
        busy = true;
        try {
          for (const entry of running()) call(entry, "update", dt);
        } finally {
          busy = false;
        }
      }
      run();
    },
    draw(alpha = 0) {
      for (const entry of showing()) call(entry, "draw", alpha);
    },
    on: events.on,
  };
  return stack;
}

/**
 * Cover the screen with a flat colour while a transition runs: call it last
 * in the render, with the stack's `cover`.
 */
export function drawCover(
  context: CanvasRenderingContext2D,
  cover: number,
  width: number,
  height: number,
  color = "#000000",
): void {
  if (cover <= 0) return;
  context.save();
  context.setTransform(1, 0, 0, 1, 0, 0);
  context.globalAlpha = Math.min(1, cover);
  context.fillStyle = color;
  context.fillRect(0, 0, width, height);
  context.restore();
}
