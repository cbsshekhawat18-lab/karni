import { act, render, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createInput, createPortal } from "../src";
import { fakePortal } from "../src/portal/adapters/fake";
import { KARNI_REGISTRY, connectPhaser, type PhaserGameLike } from "../src/engines/phaser";
import { connectPixi, type PixiAppLike } from "../src/engines/pixi";

const r3f = vi.hoisted(() => ({
  frames: [] as ((state: unknown, delta: number) => void)[],
  after: [] as (() => void)[],
  frameloop: "always",
}));

vi.mock("@react-three/fiber", () => ({
  useFrame: (callback: (state: unknown, delta: number) => void) => {
    r3f.frames.push(callback);
  },
  useThree: (select: (state: { setFrameloop: (value: string) => void }) => unknown) =>
    select({ setFrameloop: setFrameloopStable }),
  addAfterEffect: (callback: () => void) => {
    r3f.after.push(callback);
    return () => {
      r3f.after = r3f.after.filter((other) => other !== callback);
    };
  },
}));
function setFrameloopStable(value: string): void {
  r3f.frameloop = value;
}

const {
  KarniGameProvider,
  useEndInputFrame,
  useFixedStep,
  useGamePause,
  useKarniGame,
  usePortalState,
} = await import("../src/engines/r3f");

afterEach(() => {
  r3f.frames = [];
  r3f.after = [];
  r3f.frameloop = "always";
});

const phaserGame = () => {
  const listeners = new Map<string, Set<() => void>>();
  const log: string[] = [];
  const registry = new Map<string, unknown>();
  const game: PhaserGameLike & {
    fire(event: string): void;
    log: string[];
    registry: { set(k: string, v: unknown): unknown; get(k: string): unknown };
  } = {
    events: {
      on: (event, listener) => {
        const set = listeners.get(event) ?? new Set();
        set.add(listener);
        listeners.set(event, set);
      },
      off: (event, listener) => listeners.get(event)?.delete(listener),
    },
    loop: { sleep: () => log.push("sleep"), wake: () => log.push("wake") },
    sound: { mute: false },
    registry: { set: (key, value) => registry.set(key, value), get: (key) => registry.get(key) },
    fire: (event) => {
      for (const listener of listeners.get(event) ?? []) listener();
    },
    log,
  };
  return game;
};

describe("connectPhaser", () => {
  it("puts the services in the registry, sleeps and mutes Phaser for ads and blur", async () => {
    vi.useFakeTimers();
    const game = phaserGame();
    const portal = createPortal(fakePortal({ adMs: 100 }));
    await portal.init();
    const link = connectPhaser(game, { portal });
    expect(game.registry.get(KARNI_REGISTRY.portal)).toBe(portal);
    expect(game.registry.get(KARNI_REGISTRY.link)).toBe(link);
    const ad = portal.interstitial();
    expect(game.sound.mute).toBe(true);
    expect(link.paused).toBe(true);
    game.fire("blur");
    await vi.advanceTimersByTimeAsync(100);
    await ad;
    expect(link.paused).toBe(true); // still blurred
    expect(game.sound.mute).toBe(false);
    game.fire("focus");
    expect(game.log).toEqual(["sleep", "wake"]);
    link.setMuted("player", true);
    expect(game.sound.mute).toBe(true);
    link.disconnect();
    game.fire("blur");
    expect(link.paused).toBe(false);
    vi.useRealTimers();
  });
});

describe("connectPixi", () => {
  it("runs a fixed step on Pixi's ticker and stops the ticker for each pause reason", () => {
    const listeners: (() => void)[] = [];
    const log: string[] = [];
    const app: PixiAppLike & { tick(ms: number): void } = {
      ticker: {
        deltaMS: 16,
        add: (listener) => listeners.push(listener),
        remove: (listener) => listeners.splice(listeners.indexOf(listener), 1),
        start: () => log.push("start"),
        stop: () => log.push("stop"),
      },
      tick(ms) {
        (this.ticker as { deltaMS: number }).deltaMS = ms;
        for (const listener of [...listeners]) listener();
      },
    };
    const steps: number[] = [];
    let after = 0;
    const link = connectPixi(app, {
      step: 0.01,
      update: (dt) => steps.push(dt),
      afterTick: () => (after += 1),
      pauseOnHidden: false,
    });
    app.tick(25);
    expect(steps).toEqual([0.01, 0.01]);
    expect(after).toBe(1);
    app.tick(1000); // clamped to 0.05: five steps, no spiral
    expect(steps).toHaveLength(7);
    link.pause("menu");
    link.pause("ad");
    link.resume("menu");
    link.resume("ad");
    expect(log).toEqual(["stop", "start"]);
    link.disconnect();
    app.tick(25);
    expect(steps).toHaveLength(7);
  });
});

describe("the React Three Fiber hooks", () => {
  it("runs a fixed step inside useFrame", () => {
    const steps: number[] = [];
    renderHook(() => useFixedStep((dt) => steps.push(dt), { step: 0.02 }));
    act(() => r3f.frames[0]?.({}, 0.05));
    expect(steps).toEqual([0.02, 0.02]);
  });

  it("clears input edges after every frame and shares the services", () => {
    const input = createInput();
    const { result } = renderHook(
      () => {
        useEndInputFrame();
        return useKarniGame();
      },
      {
        wrapper: ({ children }) => (
          <KarniGameProvider value={{ input }}>{children}</KarniGameProvider>
        ),
      },
    );
    expect(result.current.input).toBe(input);
    input.press("Space");
    expect(input.pressed("Space")).toBe(true);
    for (const effect of r3f.after) effect();
    expect(input.pressed("Space")).toBe(false);
    input.destroy();
  });

  it("stops the frame loop for ads and hidden tabs, and tracks the portal's state", async () => {
    vi.useFakeTimers();
    const portal = createPortal(fakePortal({ adMs: 100 }));
    await portal.init();
    const states: string[] = [];
    function Probe() {
      const pause = useGamePause({ portal });
      const state = usePortalState(portal);
      states.push(`${pause.paused}:${state.adPlaying ?? "none"}`);
      return null;
    }
    render(<Probe />);
    let ad: Promise<unknown> = Promise.resolve();
    act(() => {
      ad = portal.rewarded();
    });
    expect(r3f.frameloop).toBe("never");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
      await ad;
    });
    expect(r3f.frameloop).toBe("always");
    expect(states.at(0)).toBe("false:none");
    expect(states).toContain("true:rewarded");
    expect(states.at(-1)).toBe("false:none");
    vi.useRealTimers();
  });
});
