import { describe, expect, it, vi } from "vitest";
import {
  createEntityList,
  createSceneStack,
  createStore,
  drawCover,
  type Scene,
  type SceneServices,
} from "@karni/game/scenes";
import { createLoop, createSave, createStorage, memoryStorage } from "@karni/game";

const log: string[] = [];
const named = (name: string, extra: Partial<Scene> = {}): Scene => ({
  name,
  enter: () => void log.push(`${name}:enter`),
  exit: () => void log.push(`${name}:exit`),
  pause: () => void log.push(`${name}:pause`),
  resume: () => void log.push(`${name}:resume`),
  update: (_context, dt) => void log.push(`${name}:update:${dt}`),
  draw: () => void log.push(`${name}:draw`),
  ...extra,
});
const fresh = (reducedMotion = false) => {
  log.length = 0;
  return createSceneStack({ services: {} as SceneServices, reducedMotion: () => reducedMotion });
};

describe("the scene stack", () => {
  it("pushes, pops and replaces with enter, exit, pause and resume in order", () => {
    const stack = fresh();
    stack.push(named("title"));
    stack.push(named("play"));
    expect(stack.names).toEqual(["title", "play"]);
    stack.replace(named("over"));
    stack.pop();
    stack.pop();
    expect(log).toEqual([
      "title:enter",
      "title:pause",
      "play:enter",
      "play:exit",
      "over:enter",
      "over:exit",
      "title:resume",
      "title:exit",
    ]);
    expect(stack.depth).toBe(0);
    expect(stack.top).toBeNull();
    stack.pop();
    expect(stack.depth).toBe(0);
  });

  it("updates and draws only the top scene when it is a full scene", () => {
    const stack = fresh();
    stack.push(named("title"));
    stack.push(named("play"));
    log.length = 0;
    stack.update(0.5);
    stack.draw(0.25);
    expect(log).toEqual(["play:update:0.5", "play:draw"]);
  });

  it("draws an overlay over the scene below and pauses that scene", () => {
    const stack = fresh();
    stack.push(named("play"));
    stack.push(named("pause"), { overlay: true });
    log.length = 0;
    stack.update(1);
    stack.draw();
    expect(log).toEqual(["pause:update:1", "play:draw", "pause:draw"]);
    stack.pop();
    log.length = 0;
    stack.update(1);
    expect(log).toEqual(["play:update:1"]);
  });

  it("lets an overlay that does not pause keep the scene below running", () => {
    const stack = fresh();
    stack.push(named("play"));
    stack.push(named("hud"), { overlay: true, pauses: false });
    log.length = 0;
    stack.update(1);
    expect(log).toEqual(["play:update:1", "hud:update:1"]);
  });

  it("reads overlay from the scene when the push does not say", () => {
    const stack = fresh();
    stack.push(named("play"));
    stack.push(named("dialog", { overlay: true }));
    log.length = 0;
    stack.draw();
    expect(log).toEqual(["play:draw", "dialog:draw"]);
  });

  it("hands each scene its services, its data and the stack", () => {
    const loop = createLoop({ update: () => undefined });
    const stack = createSceneStack<SceneServices & { name: string }>({
      services: { loop, name: "services" },
    });
    let seen: unknown[] = [];
    stack.push<{ level: number }>(
      {
        enter: ({ services, stack: owner, data }) => {
          seen = [services.loop === loop, services.name, owner === stack, data.level];
        },
      },
      { data: { level: 4 } },
    );
    expect(seen).toEqual([true, "services", true, 4]);
  });

  it("applies a change asked for inside update after the update", () => {
    const stack = fresh();
    stack.push(
      named("play", {
        update: (context) => {
          log.push("play:update");
          context.stack.replace(named("over"));
          log.push("play:after-ask");
        },
      }),
    );
    log.length = 0;
    stack.update(0.1);
    expect(log).toEqual(["play:update", "play:after-ask", "play:exit", "over:enter"]);
    expect(stack.top?.name).toBe("over");
  });

  it("runs changes asked for inside an enter hook in order", () => {
    const stack = fresh();
    stack.push(
      named("a", {
        enter: (context) => {
          log.push("a:enter");
          context.stack.push(named("b"));
        },
      }),
    );
    expect(stack.names).toEqual(["a", "b"]);
  });

  it("keeps going when a hook throws and reports it", () => {
    const errors: string[] = [];
    const stack = createSceneStack({
      services: {},
      onError: (_error, hook, scene) => errors.push(`${hook}:${scene.name}`),
    });
    stack.push({
      name: "bad",
      enter: () => {
        throw new Error("boom");
      },
      update: () => {
        throw new Error("boom");
      },
    });
    stack.update(0.1);
    expect(errors).toEqual(["enter:bad", "update:bad"]);
    expect(stack.depth).toBe(1);
  });

  it("emits change with the new top", () => {
    const stack = fresh();
    const seen: unknown[] = [];
    const off = stack.on("change", (value) => seen.push(value));
    stack.push(named("a"));
    stack.pop();
    off();
    stack.push(named("b"));
    expect(seen).toEqual([
      { top: "a", depth: 1 },
      { top: undefined, depth: 0 },
    ]);
  });

  it("clears every scene, top first", () => {
    const stack = fresh();
    stack.push(named("a"));
    stack.push(named("b"));
    log.length = 0;
    stack.clear();
    expect(log).toEqual(["b:exit", "a:exit"]);
  });
});

describe("transitions", () => {
  it("fades out, swaps in the middle and fades in, with the scenes still while it fades out", () => {
    const stack = fresh();
    stack.push(named("title"));
    stack.replace(named("play"), { duration: 1 });
    expect(stack.transitioning).toBe(true);
    expect(stack.top?.name).toBe("title");
    log.length = 0;
    stack.update(0.25);
    expect(stack.cover).toBeCloseTo(0.5);
    expect(log).toEqual([]);
    stack.update(0.25);
    expect(stack.cover).toBeCloseTo(1);
    // The swap happened at the midpoint, and the new scene updates as it fades in.
    expect(log).toEqual(["title:exit", "play:enter", "play:update:0.25"]);
    stack.update(0.25);
    expect(stack.cover).toBeCloseTo(0.5);
    stack.update(0.25);
    expect(stack.cover).toBe(0);
    expect(stack.transitioning).toBe(false);
  });

  it("is instant when the player prefers reduced motion", () => {
    const stack = fresh(true);
    stack.push(named("title"));
    stack.replace(named("play"), { duration: 5 });
    expect(stack.transitioning).toBe(false);
    expect(stack.top?.name).toBe("play");
    expect(stack.cover).toBe(0);
  });

  it("reads the reduced-motion setting when the change is asked for", () => {
    let reduced = false;
    const stack = createSceneStack({ services: {}, reducedMotion: () => reduced });
    stack.push({ name: "a" });
    stack.push({ name: "b" }, { duration: 1 });
    expect(stack.transitioning).toBe(true);
    stack.update(1);
    stack.update(1);
    expect(stack.transitioning).toBe(false);
    reduced = true;
    stack.pop({ duration: 1 });
    expect(stack.top?.name).toBe("a");
  });

  it("queues changes asked for while one is fading, and runs them in order", () => {
    const stack = fresh();
    stack.push(named("a"));
    stack.push(named("b"), { duration: 0.2 });
    stack.push(named("c"));
    expect(stack.names).toEqual(["a"]);
    stack.update(0.1);
    expect(stack.names).toEqual(["a", "b"]);
    expect(stack.transitioning).toBe(true);
    stack.update(0.1);
    expect(stack.names).toEqual(["a", "b", "c"]);
    expect(stack.transitioning).toBe(false);
  });

  it("falls back to matchMedia for reduced motion", () => {
    const matchMedia = vi.fn().mockReturnValue({ matches: true });
    vi.stubGlobal("matchMedia", matchMedia);
    window.matchMedia = matchMedia;
    const stack = createSceneStack({ services: {} });
    stack.push({ name: "a" });
    stack.push({ name: "b" }, { duration: 1 });
    expect(stack.top?.name).toBe("b");
    vi.unstubAllGlobals();
  });

  it("draws the cover as a flat fill, and nothing at 0", () => {
    const context = {
      save: vi.fn(),
      restore: vi.fn(),
      setTransform: vi.fn(),
      fillRect: vi.fn(),
      globalAlpha: 1,
      fillStyle: "",
    } as unknown as CanvasRenderingContext2D;
    drawCover(context, 0, 10, 10);
    expect(context.fillRect).not.toHaveBeenCalled();
    drawCover(context, 0.5, 10, 20, "#112233");
    expect(context.fillRect).toHaveBeenCalledWith(0, 0, 10, 20);
    expect(context.fillStyle).toBe("#112233");
  });
});

describe("the entity list", () => {
  interface Thing {
    id: number;
  }
  const make = (n: number): Thing[] => Array.from({ length: n }, (_, id) => ({ id }));

  it("keeps order, finds by tag and counts", () => {
    const list = createEntityList<Thing>();
    const [a, b, c] = make(3) as [Thing, Thing, Thing];
    list.add(a, "enemy");
    list.add(b, "coin", "pickup");
    list.add(c, "enemy");
    expect(list.size).toBe(3);
    expect(list.byTag("enemy")).toEqual([a, c]);
    expect(list.tagged(b, "pickup")).toBe(true);
    expect([...list]).toEqual([a, b, c]);
    expect(list.add(a, "boss")).toBe(a);
    expect(list.size).toBe(3);
    expect(list.byTag("boss")).toEqual([a]);
  });

  it("removes during a loop without skipping or visiting a removed one", () => {
    const list = createEntityList<Thing>();
    const things = make(5);
    for (const thing of things) list.add(thing, "t");
    const visited: number[] = [];
    list.each((thing) => {
      visited.push(thing.id);
      if (thing.id === 1) {
        list.remove(things[1] as Thing);
        list.remove(things[2] as Thing);
      }
    });
    expect(visited).toEqual([0, 1, 3, 4]);
    expect(list.size).toBe(3);
    expect([...list].map((t) => t.id)).toEqual([0, 3, 4]);
  });

  it("leaves what is added in a loop for the next loop", () => {
    const list = createEntityList<Thing>();
    list.add({ id: 0 });
    const visited: number[] = [];
    list.each((thing) => {
      visited.push(thing.id);
      if (thing.id < 3) list.add({ id: thing.id + 1 });
    });
    expect(visited).toEqual([0]);
    expect(list.size).toBe(2);
  });

  it("removes by tag and by test, and reports what it did", () => {
    const list = createEntityList<Thing>();
    for (const thing of make(6)) list.add(thing, thing.id % 2 ? "odd" : "even");
    expect(list.removeTagged("odd")).toBe(3);
    expect(list.removeWhere((thing) => thing.id === 0)).toBe(1);
    expect([...list].map((t) => t.id)).toEqual([2, 4]);
    expect(list.remove({ id: 99 })).toBe(false);
    list.clear();
    expect(list.size).toBe(0);
  });

  it("takes an entity back that was removed and added in one loop", () => {
    const list = createEntityList<Thing>();
    const [a, b] = make(2) as [Thing, Thing];
    list.add(a);
    list.add(b);
    list.each((thing) => {
      if (thing === a) {
        list.remove(a);
        list.add(a, "again");
      }
    });
    expect(list.size).toBe(2);
    expect(list.byTag("again")).toEqual([a]);
    expect([...list]).toEqual([a, b]);
  });

  it("loops over a tag", () => {
    const list = createEntityList<Thing>();
    const things = make(4);
    things.forEach((thing) => list.add(thing, thing.id > 1 ? "late" : "early"));
    const seen: number[] = [];
    list.eachTagged("late", (thing) => seen.push(thing.id));
    expect(seen).toEqual([2, 3]);
  });
});

describe("the store", () => {
  interface Progress {
    best: number;
    stars: Record<string, number>;
  }
  const open = (debounceMs = 0) => {
    const storage = createStorage({ namespace: "t", backend: memoryStorage() });
    const save = createSave<Progress>({
      storage,
      version: 1,
      defaults: () => ({ best: 0, stars: {} }),
    });
    return { storage, save, store: createStore({ save, debounceMs }) };
  };

  it("starts from the save, notifies and writes through the save layer", () => {
    const { save, store } = open();
    expect(store.loaded.status).toBe("new");
    const seen: number[] = [];
    store.subscribe((state, previous) => seen.push(state.best - previous.best));
    store.set({ best: 12 });
    store.update((draft) => {
      draft.stars["a"] = 3;
    });
    expect(store.state).toEqual({ best: 12, stars: { a: 3 } });
    expect(seen).toEqual([12, 0]);
    expect(save.load().data).toEqual({ best: 12, stars: { a: 3 } });
    expect(save.load().status).toBe("loaded");
  });

  it("loads what was saved, and boots from the defaults when the save is corrupt", () => {
    const first = open();
    first.store.set({ best: 7 });
    const again = createStore({ save: first.save, debounceMs: 0 });
    expect(again.state.best).toBe(7);
    first.storage.set("save", "{not json");
    const broken = createStore({ save: first.save, debounceMs: 0 });
    expect(broken.loaded.status).toBe("corrupt");
    expect(broken.state.best).toBe(0);
  });

  it("writes once after a burst of changes, and flushes on demand", () => {
    vi.useFakeTimers();
    try {
      const { save, store } = open(250);
      const write = vi.spyOn(save, "write");
      for (let n = 1; n <= 20; n += 1) store.set({ best: n });
      expect(write).not.toHaveBeenCalled();
      vi.advanceTimersByTime(300);
      expect(write).toHaveBeenCalledTimes(1);
      store.set({ best: 99 });
      expect(store.flush()).toBe(true);
      expect(write).toHaveBeenCalledTimes(2);
      expect(save.load().data.best).toBe(99);
    } finally {
      vi.useRealTimers();
    }
  });

  it("writes when the page is hidden", () => {
    vi.useFakeTimers();
    try {
      const { save, store } = open(10_000);
      store.set({ best: 5 });
      expect(save.load().status).toBe("new");
      window.dispatchEvent(new Event("pagehide"));
      expect(save.load().data.best).toBe(5);
      store.destroy();
    } finally {
      vi.useRealTimers();
    }
  });

  it("resets to the defaults and keeps a throwing listener from stopping the others", () => {
    const { store } = open();
    const quiet = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const seen: number[] = [];
    store.subscribe(() => {
      throw new Error("bad listener");
    });
    store.subscribe((state) => seen.push(state.best));
    store.set({ best: 3 });
    store.reset();
    expect(seen).toEqual([3, 0]);
    expect(quiet).toHaveBeenCalled();
  });

  it("reports a write that storage refuses and keeps the state", () => {
    const storage = createStorage({ namespace: "t", backend: memoryStorage() });
    const save = createSave({ storage, version: 1, defaults: () => ({ best: 0 }) });
    vi.spyOn(save, "write").mockReturnValue(false);
    const refused = vi.fn();
    const store = createStore({ save, debounceMs: 0, onWriteError: refused });
    store.set({ best: 2 });
    expect(refused).toHaveBeenCalled();
    expect(store.state.best).toBe(2);
  });
});
