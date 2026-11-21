import axe from "axe-core";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createAudio, createInput, createLoop, createStorage, memoryStorage } from "@karni/game";
import {
  COLOUR_SAFE,
  applySettings,
  createDevOverlay,
  createSettings,
  createTouchButtons,
  createTranslate,
  createUi,
  guardBoot,
  keyName,
  openPause,
  openSettings,
  showBootFailure,
  type Ui,
} from "@karni/game/ui";
import { FakeAudioContext } from "./fake-audio";

/** Run axe on an element. jsdom has no layout, so the contrast rule runs in the browser test instead. */
async function violations(node: Element): Promise<string[]> {
  const result = await axe.run(node, { rules: { "color-contrast": { enabled: false } } });
  return result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(" | ")}`);
}

let ui: Ui | null = null;
const open = (options: Parameters<typeof createUi>[0] = {}): Ui => {
  ui = createUi(options);
  return ui;
};
afterEach(() => {
  ui?.destroy();
  ui = null;
  document.body.innerHTML = "";
  document.head.innerHTML = "";
  vi.useRealTimers();
});

const press = (target: EventTarget, key: string, init: KeyboardEventInit = {}): KeyboardEvent => {
  const event = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init });
  target.dispatchEvent(event);
  return event;
};
const buttonOf = (root: ParentNode, text: string): HTMLButtonElement => {
  const found = [...root.querySelectorAll("button")].find((b) => b.textContent?.includes(text));
  if (!found) throw new Error(`no button "${text}"`);
  return found;
};
const tick = () => new Promise<void>((done) => setTimeout(done, 0));

describe("the strings table", () => {
  it("fills values and replaces any word", () => {
    const t = createTranslate({ resume: "Weiter", volumeValue: "{value} Prozent" });
    expect(t("resume")).toBe("Weiter");
    expect(t("volumeValue", { value: 40 })).toBe("40 Prozent");
    expect(t("volumeValue")).toBe("{value} Prozent");
    expect(t("quit")).toBe("Quit");
  });

  it("names keys for people", () => {
    const t = createTranslate();
    expect(keyName("KeyW", t)).toBe("W");
    expect(keyName("Digit4", t)).toBe("4");
    expect(keyName("ArrowLeft", t)).toBe("Left arrow");
    expect(keyName("ShiftRight", t)).toBe("Shift");
    expect(keyName("Pointer", t)).toBe("Click or tap");
    expect(keyName("F5", t)).toBe("F5");
  });

  it("shows only words from the table in the kit, so a translation covers it all", () => {
    const strings = createTranslate({ resume: "R!", settings: "S!", pauseTitle: "P!" });
    const kit = open({ strings: { resume: "R!", settings: "S!", pauseTitle: "P!" } });
    openPause(kit, { onSettings: () => undefined });
    expect(kit.root.querySelector("h2")?.textContent).toBe(strings("pauseTitle"));
    expect(buttonOf(kit.root, "R!")).toBeTruthy();
    expect(buttonOf(kit.root, "S!")).toBeTruthy();
  });
});

describe("dialogs", () => {
  it("is a labelled modal dialog with focus on its primary action", async () => {
    const kit = open();
    kit.dialog({ title: "Saved", body: "Your game is saved." });
    const panel = kit.root.querySelector<HTMLElement>('[role="dialog"]');
    expect(panel?.getAttribute("aria-modal")).toBe("true");
    const label = panel?.getAttribute("aria-labelledby") ?? "";
    expect(document.getElementById(label)?.textContent).toBe("Saved");
    expect(document.activeElement?.textContent).toBe("OK");
    expect(await violations(kit.root)).toEqual([]);
  });

  it("resolves the chosen action, closes, and gives focus back", async () => {
    const kit = open();
    const opener = document.createElement("button");
    document.body.append(opener);
    opener.focus();
    const dialog = kit.dialog({
      title: "Pick",
      actions: [
        { id: "a", label: "Alpha" },
        { id: "b", label: "Beta", primary: true },
      ],
    });
    expect(kit.modal).toBe(true);
    buttonOf(dialog.element, "Alpha").click();
    expect(await dialog.result).toBe("a");
    expect(kit.modal).toBe(false);
    expect(dialog.open).toBe(false);
    expect(document.activeElement).toBe(opener);
  });

  it("closes on Escape with null, and not when it cannot be dismissed", async () => {
    const kit = open();
    const first = kit.dialog({ title: "One" });
    press(first.element, "Escape");
    expect(await first.result).toBeNull();
    const second = kit.dialog({ title: "Two", dismissable: false });
    press(second.element, "Escape");
    expect(second.open).toBe(true);
    second.close("done");
    expect(await second.result).toBe("done");
  });

  it("keeps Tab inside, wrapping at both ends", () => {
    const kit = open();
    const dialog = kit.dialog({
      title: "Wrap",
      actions: [
        { id: "a", label: "A" },
        { id: "b", label: "B", primary: true },
      ],
    });
    const [a, b] = [buttonOf(dialog.element, "A"), buttonOf(dialog.element, "B")];
    b.focus();
    expect(press(b, "Tab").defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(a);
    expect(press(a, "Tab", { shiftKey: true }).defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(b);
    a.focus();
    expect(press(a, "Tab").defaultPrevented).toBe(false);
  });

  it("makes everything behind it inert and never lets its keys reach the game", () => {
    const input = createInput({ bindings: { jump: ["Space"] } });
    const kit = open({ input });
    const dialog = kit.dialog({ title: "Modal" });
    expect(kit.hud.hasAttribute("inert")).toBe(true);
    press(dialog.element, " ", { code: "Space" });
    const typed = new KeyboardEvent("keydown", { code: "Space", key: " ", bubbles: true });
    buttonOf(dialog.element, "OK").dispatchEvent(typed);
    expect(input.held("jump")).toBe(false);
    dialog.close();
    expect(kit.hud.hasAttribute("inert")).toBe(false);
    input.destroy();
  });

  it("lets go of held keys when it opens", () => {
    const input = createInput({ bindings: { right: ["ArrowRight"] } });
    const kit = open({ input });
    input.press("ArrowRight");
    kit.dialog({ title: "Held" });
    expect(input.held("right")).toBe(false);
    input.destroy();
  });

  it("stacks: only the top dialog is live, and closing it frees the one below", async () => {
    const kit = open();
    const lower = kit.dialog({ title: "Lower" });
    const upper = kit.dialog({ title: "Upper" });
    expect(lower.element.parentElement?.hasAttribute("inert")).toBe(true);
    expect(upper.element.parentElement?.hasAttribute("inert")).toBe(false);
    upper.close();
    expect(lower.element.parentElement?.hasAttribute("inert")).toBe(false);
    expect(await violations(kit.root)).toEqual([]);
  });

  it("asks a question with confirm, starting a destructive one on the safe answer", async () => {
    const kit = open();
    const asked = kit.confirm({ title: "Delete?", danger: true, confirmLabel: "Delete" });
    expect(document.activeElement?.textContent).toBe("Cancel");
    buttonOf(kit.root, "Delete").click();
    expect(await asked).toBe(true);
    const again = kit.confirm({ title: "Sure?" });
    press(kit.root.querySelector<HTMLElement>('[role="alertdialog"]') as HTMLElement, "Escape");
    expect(await again).toBe(false);
  });

  it("keeps a dialog open for a keepOpen action", async () => {
    const kit = open();
    const seen: string[] = [];
    const dialog = kit.dialog({
      title: "Menu",
      actions: [
        { id: "more", label: "More", keepOpen: true },
        { id: "go", label: "Go" },
      ],
      onAction: (id) => seen.push(id),
    });
    buttonOf(dialog.element, "More").click();
    expect(dialog.open).toBe(true);
    buttonOf(dialog.element, "Go").click();
    expect(seen).toEqual(["more", "go"]);
    expect(await dialog.result).toBe("go");
  });
});

describe("screens and toasts", () => {
  it("shows a labelled screen with its primary action focused, and Enter does not reach the game", async () => {
    const kit = open();
    const chosen: string[] = [];
    const screen = kit.screen({
      title: "Block Hopper",
      text: "Hop across the blocks.",
      actions: [
        { id: "play", label: "Play", primary: true },
        { id: "settings", label: "Settings" },
      ],
      onAction: (id) => chosen.push(id),
    });
    expect(document.activeElement?.textContent).toBe("Play");
    const seen = vi.fn();
    window.addEventListener("keydown", seen);
    press(document.activeElement as HTMLElement, "Enter");
    expect(seen).not.toHaveBeenCalled();
    window.removeEventListener("keydown", seen);
    buttonOf(screen.element, "Play").click();
    expect(chosen).toEqual(["play"]);
    expect(await violations(kit.root)).toEqual([]);
    screen.close();
    expect(kit.root.querySelector("section")).toBeNull();
  });

  it("announces a toast and gives an error the alert role", async () => {
    const kit = open();
    kit.toast("Saved");
    kit.toast("Could not save", { kind: "error" });
    expect(kit.root.querySelector('[role="status"]')?.textContent).toContain("Saved");
    expect(kit.root.querySelector('[role="alert"]')?.textContent).toContain("Could not save");
    expect(await violations(kit.root)).toEqual([]);
  });

  it("removes a toast on time", () => {
    vi.useFakeTimers();
    const kit = open();
    kit.toast("Saved");
    kit.toast("Could not save", { kind: "error" });
    vi.advanceTimersByTime(4100);
    expect(kit.root.querySelector('[role="status"]')).toBeNull();
    expect(kit.root.querySelector('[role="alert"]')).not.toBeNull();
    vi.advanceTimersByTime(4000);
    expect(kit.root.querySelector(".kg-toast")).toBeNull();
  });

  it("keeps three toasts at most, and a sticky one until it is dismissed", () => {
    const kit = open();
    for (let n = 0; n < 5; n += 1) kit.toast(`Toast ${n}`, { durationMs: 0 });
    const shown = [...kit.root.querySelectorAll(".kg-toast-text")].map((n) => n.textContent);
    expect(shown).toEqual(["Toast 2", "Toast 3", "Toast 4"]);
    buttonOf(kit.root, "Dismiss").click();
    expect(kit.root.querySelectorAll(".kg-toast")).toHaveLength(2);
  });
});

describe("settings", () => {
  const setup = () => {
    const storage = createStorage({ namespace: "g", backend: memoryStorage() });
    const store = createSettings({ storage, debounceMs: 0 });
    const kit = open();
    return { storage, store, kit };
  };

  it("keeps settings in their own save and loads them again", () => {
    const { storage, store } = setup();
    store.set({ master: 0.4, colourSafe: true });
    const again = createSettings({ storage, debounceMs: 0 });
    expect(again.state).toMatchObject({ master: 0.4, colourSafe: true, muted: false });
    expect(storage.keys()).toContain("settings");
  });

  it("makes the audio, the palette and reduced motion follow the settings", () => {
    const { store, kit } = setup();
    const audio = createAudio({ createContext: () => new FakeAudioContext() as never });
    const stop = applySettings({ store, audio, ui: kit });
    store.set({ master: 0.5, music: 0.25, muted: true, colourSafe: true, reducedMotion: true });
    expect(audio.volume("master")).toBe(0.5);
    expect(audio.volume("music")).toBe(0.25);
    expect(audio.isMuted("player")).toBe(true);
    expect(kit.root.getAttribute("data-kg-palette")).toBe("safe");
    expect(kit.root.getAttribute("data-kg-motion")).toBe("reduced");
    stop();
    store.set({ master: 1 });
    expect(audio.volume("master")).toBe(0.5);
  });

  it("changes the store from the dialog: sliders, mute, reduced motion and the palette", async () => {
    const { store, kit } = setup();
    const dialog = openSettings(kit, { store });
    const range = dialog.element.querySelector<HTMLInputElement>('input[type="range"]');
    if (!range) throw new Error("no slider");
    range.value = "40";
    range.dispatchEvent(new Event("input", { bubbles: true }));
    expect(store.state.master).toBeCloseTo(0.4);
    expect(range.getAttribute("aria-valuetext")).toBe("40%");
    for (const [label, field] of [
      ["Mute all sound", "muted"],
      ["Reduced motion", "reducedMotion"],
      ["Colour-safe palette", "colourSafe"],
    ] as const) {
      const box = [...dialog.element.querySelectorAll("label")].find((l) =>
        l.textContent?.startsWith(label),
      )?.control as HTMLInputElement;
      box.checked = true;
      box.dispatchEvent(new Event("change", { bubbles: true }));
      expect(store.state[field]).toBe(true);
    }
    expect(await violations(kit.root)).toEqual([]);
  });

  it("remaps a control with the next key, keeps the pointer code, and says so", () => {
    const { store, kit } = setup();
    const input = createInput({ bindings: { jump: ["Space", "Pointer"], left: ["ArrowLeft"] } });
    applySettings({ store, input });
    const controls = [
      { action: "jump", label: "Jump", codes: ["Space", "Pointer"] },
      { action: "left", label: "Left", codes: ["ArrowLeft"] },
    ];
    const dialog = openSettings(kit, { store, controls });
    expect(buttonOf(dialog.element, "Jump:").textContent).toBe("Jump: Space");
    buttonOf(dialog.element, "Jump:").click();
    expect(buttonOf(dialog.element, "Press a key").getAttribute("aria-pressed")).toBe("true");
    const event = new KeyboardEvent("keydown", {
      code: "KeyJ",
      key: "j",
      bubbles: true,
      cancelable: true,
    });
    document.body.dispatchEvent(event);
    expect(store.state.bindings.jump).toEqual(["KeyJ", "Pointer"]);
    expect(buttonOf(dialog.element, "Jump:").textContent).toBe("Jump: J");
    expect(dialog.element.querySelector('[role="status"]')?.textContent).toBe("Jump is now J");
    // The input follows, and the old key no longer jumps.
    window.dispatchEvent(new KeyboardEvent("keydown", { code: "KeyJ" }));
    expect(input.pressed("jump")).toBe(true);
    input.endFrame();
    window.dispatchEvent(new KeyboardEvent("keyup", { code: "KeyJ" }));
    window.dispatchEvent(new KeyboardEvent("keydown", { code: "Space" }));
    expect(input.pressed("jump")).toBe(false);
    input.destroy();
  });

  it("takes a key from another action and reports it, cancels on Escape, and resets", () => {
    const { store, kit } = setup();
    const controls = [
      { action: "jump", label: "Jump", codes: ["Space"] },
      { action: "left", label: "Left", codes: ["ArrowLeft"] },
    ];
    const dialog = openSettings(kit, { store, controls });
    buttonOf(dialog.element, "Jump:").click();
    document.body.dispatchEvent(
      new KeyboardEvent("keydown", { code: "ArrowLeft", key: "ArrowLeft", bubbles: true }),
    );
    expect(store.state.bindings.left).toEqual([]);
    expect(buttonOf(dialog.element, "Left:").textContent).toBe("Left: No key");
    expect(dialog.element.querySelector('[role="status"]')?.textContent).toContain(
      "Left, which now has no key",
    );
    buttonOf(dialog.element, "Left:").click();
    document.body.dispatchEvent(
      new KeyboardEvent("keydown", { code: "Escape", key: "Escape", bubbles: true }),
    );
    expect(dialog.open).toBe(true);
    expect(store.state.bindings.left).toEqual([]);
    buttonOf(dialog.element, "Reset controls").click();
    expect(store.state.bindings).toEqual({ jump: ["Space"], left: ["ArrowLeft"] });
  });

  it("writes the settings when the dialog closes", () => {
    const storage = createStorage({ namespace: "g", backend: memoryStorage() });
    const store = createSettings({ storage, debounceMs: 60_000 });
    const kit = open();
    const dialog = openSettings(kit, { store });
    store.set({ effects: 0.2 });
    expect(storage.get("settings")).toBeNull();
    dialog.close();
    expect(JSON.parse(storage.get("settings") ?? "{}").data.effects).toBe(0.2);
  });

  it("offers the palette as data for the game to draw with", () => {
    expect(Object.values(COLOUR_SAFE)).toHaveLength(8);
    expect(COLOUR_SAFE.blue).toMatch(/^#[0-9a-f]{6}$/);
  });
});

describe("the pause menu", () => {
  it("pauses the loop while open, resumes on Escape, and keeps itself open behind settings", async () => {
    const loop = createLoop({ update: () => undefined });
    const kit = open();
    const onSettings = vi.fn();
    const onResume = vi.fn();
    const menu = openPause(kit, { loop, onSettings, onResume });
    expect(loop.pauseReasons.has("menu")).toBe(true);
    expect(document.activeElement?.textContent).toBe("Resume");
    buttonOf(menu.element, "Settings").click();
    expect(onSettings).toHaveBeenCalled();
    expect(menu.open).toBe(true);
    expect(await violations(kit.root)).toEqual([]);
    press(menu.element, "Escape");
    expect(await menu.result).toBeNull();
    expect(loop.paused).toBe(false);
    expect(onResume).toHaveBeenCalled();
  });

  it("asks before it quits, and quits on yes", async () => {
    const kit = open();
    const onQuit = vi.fn();
    const menu = openPause(kit, { onQuit });
    buttonOf(menu.element, "Quit").click();
    expect(kit.root.querySelector('[role="alertdialog"]')).not.toBeNull();
    buttonOf(kit.root.querySelector('[role="alertdialog"]') as HTMLElement, "Cancel").click();
    await tick();
    expect(onQuit).not.toHaveBeenCalled();
    expect(menu.open).toBe(true);
    buttonOf(menu.element, "Quit").click();
    buttonOf(kit.root.querySelector('[role="alertdialog"]') as HTMLElement, "Quit").click();
    expect(await menu.result).toBe("quit");
    expect(onQuit).toHaveBeenCalledOnce();
  });
});

describe("touch buttons", () => {
  const pointer = (target: Element, type: string): void => {
    const event = new MouseEvent(type, { bubbles: true, cancelable: true });
    Object.defineProperty(event, "pointerId", { value: 7 });
    Object.defineProperty(event, "pointerType", { value: "touch" });
    target.dispatchEvent(event);
  };

  it("holds the input's action while a finger is down, so one binding serves every device", async () => {
    const input = createInput({ bindings: { jump: ["Space"] } });
    const kit = open();
    const buttons = createTouchButtons(kit, input, [
      { action: "jump", label: "Jump", side: "right" },
      { action: "left", label: "Left", side: "left" },
    ]);
    const jump = buttonOf(buttons.element, "Jump");
    pointer(jump, "pointerdown");
    expect(input.held("jump")).toBe(true);
    expect(input.pressed("jump")).toBe(true);
    expect(jump.hasAttribute("data-kg-down")).toBe(true);
    pointer(jump, "pointerup");
    expect(input.held("jump")).toBe(false);
    expect(input.released("jump")).toBe(true);
    expect(await violations(kit.root)).toEqual([]);
    input.destroy();
  });

  it("does not let the press reach the canvas, and lets go on cancel and on destroy", () => {
    const input = createInput({ bindings: { jump: ["Space"] } });
    const kit = open();
    const buttons = createTouchButtons(kit, input, [{ action: "jump", label: "Jump" }]);
    const reached = vi.fn();
    window.addEventListener("pointerdown", reached);
    const jump = buttonOf(buttons.element, "Jump");
    pointer(jump, "pointerdown");
    expect(reached).not.toHaveBeenCalled();
    window.removeEventListener("pointerdown", reached);
    pointer(jump, "pointercancel");
    expect(input.held("jump")).toBe(false);
    pointer(jump, "pointerdown");
    buttons.destroy();
    expect(input.held("jump")).toBe(false);
    expect(kit.hud.querySelector(".kg-touch")).toBeNull();
    input.destroy();
  });

  it("works from the keyboard and shows on the first touch", () => {
    const input = createInput({ bindings: { jump: ["Space"] } });
    const kit = open();
    const buttons = createTouchButtons(kit, input, [{ action: "jump", label: "Jump" }]);
    const jump = buttonOf(buttons.element, "Jump");
    expect(buttons.element.hasAttribute("data-kg-show")).toBe(false);
    pointer(document.body, "pointerdown");
    expect(buttons.element.hasAttribute("data-kg-show")).toBe(true);
    press(jump, "Enter");
    expect(input.held("jump")).toBe(true);
    jump.dispatchEvent(new KeyboardEvent("keyup", { key: "Enter", bubbles: true }));
    expect(input.held("jump")).toBe(false);
    buttons.show(false);
    expect(buttons.element.hasAttribute("data-kg-hide")).toBe(true);
    input.destroy();
  });
});

describe("the boot failure screen", () => {
  it("is an alert the player can read, with details and a Try again that runs onRetry", async () => {
    const onRetry = vi.fn();
    const failure = showBootFailure({ error: new Error("no WebGL"), onRetry });
    const card = failure.element;
    expect(card.getAttribute("role")).toBe("alert");
    expect(card.querySelector("h1")?.textContent).toBe("The game could not start");
    expect(card.querySelector("pre")?.textContent).toContain("no WebGL");
    expect(document.activeElement?.textContent).toBe("Try again");
    buttonOf(card, "Try again").click();
    expect(onRetry).toHaveBeenCalled();
    expect(await violations(card)).toEqual([]);
    failure.destroy();
    expect(document.querySelector(".kg-boot")).toBeNull();
  });

  it("takes its words from the strings table", () => {
    const failure = showBootFailure({
      title: "Kein Start",
      strings: { retry: "Nochmal", details: "Einzelheiten" },
      error: "x",
    });
    expect(failure.element.textContent).toContain("Kein Start");
    expect(buttonOf(failure.element, "Nochmal")).toBeTruthy();
    expect(failure.element.querySelector("summary")?.textContent).toBe("Einzelheiten");
  });

  it("guards a start: runs it, shows the screen when it throws, and runs it again on retry", async () => {
    let attempts = 0;
    const boot = vi.fn(async () => {
      attempts += 1;
      if (attempts === 1) throw new Error("asset failed");
    });
    expect(await guardBoot(boot)).toBe(false);
    expect(document.querySelector(".kg-boot pre")?.textContent).toContain("asset failed");
    buttonOf(document.body, "Try again").click();
    await tick();
    expect(boot).toHaveBeenCalledTimes(2);
    expect(document.querySelector(".kg-boot")).toBeNull();
    expect(await guardBoot(async () => undefined)).toBe(true);
  });
});

describe("the dev overlay", () => {
  const frames = () => {
    let at = 0;
    let pending: (() => void) | null = null;
    return {
      now: () => at,
      requestFrame: (cb: () => void) => {
        pending = cb;
        return 1;
      },
      cancelFrame: () => {
        pending = null;
      },
      run(count: number, ms: number) {
        for (let n = 0; n < count; n += 1) {
          at += ms;
          const cb = pending;
          pending = null;
          cb?.();
        }
      },
    };
  };

  it("is off outside development and adds nothing to the page", () => {
    const kit = open();
    const loop = createLoop({ update: () => undefined, step: 1 / 60 });
    const overlay = createDevOverlay(kit, { loop, ...frames() });
    expect(overlay.element).toBeNull();
    expect(kit.root.querySelector(".kg-dev")).toBeNull();
  });

  it("shows frame time, steps per frame and the entity count when enabled", () => {
    const kit = open();
    const loop = createLoop({ update: () => undefined, step: 1 / 60 });
    const clock = frames();
    let count = 3;
    const overlay = createDevOverlay(kit, { loop, enabled: true, entities: () => count, ...clock });
    loop.tick(1 / 30);
    clock.run(20, 20);
    const text = overlay.element?.textContent ?? "";
    expect(text).toContain("frame 20.0 ms");
    expect(text).toContain("steps 2");
    expect(text).toContain("entities 3");
    count = 9;
    loop.tick(1 / 60);
    clock.run(20, 10);
    expect(overlay.element?.textContent).toContain("entities 9");
    expect(overlay.element?.getAttribute("aria-hidden")).toBe("true");
    overlay.destroy();
    expect(kit.root.querySelector(".kg-dev")).toBeNull();
  });
});

describe("the layer", () => {
  it("follows the theme and removes itself", () => {
    const kit = open({ theme: "dark" });
    expect(kit.root.getAttribute("data-kg-theme")).toBe("dark");
    kit.setTheme("light");
    expect(kit.root.getAttribute("data-kg-theme")).toBe("light");
    expect(document.getElementById("kg-ui-style")?.textContent).toContain(
      "prefers-color-scheme: dark",
    );
    kit.dialog({ title: "Open" });
    kit.destroy();
    expect(document.querySelector(".kg-root")).toBeNull();
  });

  it("makes the stylesheet once for any number of layers", () => {
    open();
    const second = createUi();
    second.destroy();
    expect(document.querySelectorAll("#kg-ui-style")).toHaveLength(1);
  });

  it("leaves the stylesheet to the game when asked", () => {
    const kit = open({ styles: false });
    expect(document.getElementById("kg-ui-style")).toBeNull();
    kit.destroy();
  });
});
