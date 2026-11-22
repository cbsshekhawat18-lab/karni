import type { GameAudio } from "../audio/audio";
import type { Input } from "../input/input";
import { createSave } from "../save/save";
import type { GameStorage } from "../save/storage";
import { createStore, type Store } from "../scenes/store";
import { el, uid } from "./dom";
import { keyName } from "./strings";
import type { DialogHandle, Ui } from "./ui";

/** What a player can change. Plain JSON, kept in the save layer. */
export interface Settings {
  /** Volumes from 0 to 1. */
  master: number;
  music: number;
  effects: number;
  muted: boolean;
  reducedMotion: boolean;
  colourSafe: boolean;
  /** Remapped controls by action: the key codes (and any pointer or stick codes) that trigger it. Empty until the player changes one. */
  bindings: Record<string, string[]>;
}

/** The settings of a new player. Reduced motion starts from the system's setting. */
export function defaultSettings(): Settings {
  const reduced =
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  return {
    master: 1,
    music: 1,
    effects: 1,
    muted: false,
    reducedMotion: reduced,
    colourSafe: false,
    bindings: {},
  };
}

export interface SettingsStoreOptions {
  storage: GameStorage;
  /** The key inside the storage's namespace. Default "settings". */
  key?: string;
  /** Settings a game adds are merged over these, so give it the defaults you want. */
  defaults?: () => Settings;
  debounceMs?: number;
}

/** The settings as a store on the save layer, with its own key so a game's progress save is untouched. */
export function createSettings(options: SettingsStoreOptions): Store<Settings> {
  const defaults = options.defaults ?? defaultSettings;
  const save = createSave<Settings>({
    storage: options.storage,
    key: options.key ?? "settings",
    version: 1,
    defaults,
  });
  return createStore({ save, defaults, debounceMs: options.debounceMs });
}

export interface ApplySettingsOptions {
  store: Store<Settings>;
  audio?: Pick<GameAudio, "setVolume" | "setMuted">;
  input?: Pick<Input, "bind">;
  ui?: Pick<Ui, "setPalette" | "setReducedMotion">;
}

/**
 * Make the game follow the settings now and after every change: volumes and
 * mute on the audio, remapped controls on the input, the palette and reduced
 * motion on the kit. Returns the function that stops it.
 */
export function applySettings(options: ApplySettingsOptions): () => void {
  const { store, audio, input, ui } = options;
  let bound = new Map<string, string>();
  const apply = (settings: Readonly<Settings>): void => {
    if (audio) {
      audio.setVolume("master", settings.master);
      audio.setVolume("music", settings.music);
      audio.setVolume("effects", settings.effects);
      audio.setMuted("player", settings.muted);
    }
    ui?.setPalette(settings.colourSafe ? "safe" : "default");
    ui?.setReducedMotion(settings.reducedMotion);
    if (input) {
      for (const [action, codes] of Object.entries(settings.bindings)) {
        const key = codes.join(",");
        if (bound.get(action) === key) continue;
        bound.set(action, key);
        input.bind(action, codes);
      }
    }
  };
  apply(store.state);
  const off = store.subscribe(apply);
  return () => {
    off();
    bound = new Map();
  };
}

/** One remappable action. `codes` are its defaults, and what "Reset controls" goes back to. */
export interface ControlSpec {
  action: string;
  /** Shown to the player: "Jump". */
  label: string;
  codes: readonly string[];
}

export interface SettingsDialogOptions {
  store: Store<Settings>;
  /** The actions the player may remap. Omit for a game with fixed controls. */
  controls?: readonly ControlSpec[];
  /** Hide the colour-safe switch for a game with no palette of its own. Default true. */
  showColourSafe?: boolean;
  onClose?(): void;
}

/** A code that is a keyboard key, as opposed to the pointer or the stick, which a remap keeps. */
const isKey = (code: string): boolean => !/^(Pointer|Stick)/.test(code);

/**
 * The settings dialog: volumes, mute, reduced motion, the colour-safe palette
 * and key remapping. It changes the store, and `applySettings` does the rest.
 */
export function openSettings(ui: Ui, options: SettingsDialogOptions): DialogHandle {
  const { store, t } = { store: options.store, t: ui.t };
  const live = el("div", { class: "kg-hint", role: "status" });

  const group = (heading: string, ...rows: HTMLElement[]): HTMLElement =>
    el("fieldset", { class: "kg-group" }, el("legend", {}, heading), ...rows);

  const slider = (label: string, field: "master" | "music" | "effects"): HTMLElement => {
    const id = uid("kg-vol");
    const input = el("input", {
      id,
      type: "range",
      min: "0",
      max: "100",
      step: "5",
      value: String(Math.round(store.state[field] * 100)),
    });
    const output = el("output", { for: id });
    const show = (): void => {
      output.textContent = t("volumeValue", { value: input.value });
      input.setAttribute("aria-valuetext", output.textContent);
    };
    show();
    input.addEventListener("input", () => {
      show();
      store.set({ [field]: Number(input.value) / 100 });
    });
    return el("div", { class: "kg-row kg-slider" }, el("label", { for: id }, label), input, output);
  };

  const toggle = (
    label: string,
    field: "muted" | "reducedMotion" | "colourSafe",
    hint?: string,
  ): HTMLElement => {
    const id = uid("kg-toggle");
    const box = el("input", { id, type: "checkbox" });
    box.checked = store.state[field];
    box.addEventListener("change", () => store.set({ [field]: box.checked }));
    const hintId = hint ? `${id}-hint` : undefined;
    if (hintId) box.setAttribute("aria-describedby", hintId);
    return el(
      "div",
      { class: "kg-row" },
      el(
        "label",
        { for: id },
        label,
        hint ? el("div", { class: "kg-hint", id: hintId }, hint) : null,
      ),
      box,
    );
  };

  const sections: HTMLElement[] = [
    group(
      t("soundHeading"),
      slider(t("volumeMaster"), "master"),
      slider(t("volumeMusic"), "music"),
      slider(t("volumeEffects"), "effects"),
      toggle(t("mute"), "muted"),
    ),
    group(
      t("displayHeading"),
      toggle(t("reducedMotion"), "reducedMotion", t("reducedMotionHint")),
      ...(options.showColourSafe === false
        ? []
        : [toggle(t("colourSafe"), "colourSafe", t("colourSafeHint"))]),
    ),
  ];

  const controls = options.controls ?? [];
  let cancelCapture: (() => void) | null = null;
  if (controls.length > 0) {
    const codesOf = (spec: ControlSpec): readonly string[] =>
      store.state.bindings[spec.action] ?? spec.codes;
    const buttons = new Map<string, HTMLButtonElement>();
    const describe = (spec: ControlSpec): string => {
      const keys = codesOf(spec)
        .filter(isKey)
        .map((code) => keyName(code, t));
      return `${spec.label}: ${keys.length > 0 ? keys.join(", ") : t("controlNone")}`;
    };
    const refresh = (): void => {
      for (const spec of controls) {
        const button = buttons.get(spec.action);
        if (button) button.textContent = describe(spec);
      }
    };
    const assign = (spec: ControlSpec, code: string): void => {
      const bindings: Record<string, string[]> = { ...store.state.bindings };
      let taken: ControlSpec | undefined;
      for (const other of controls) {
        if (other.action === spec.action || !codesOf(other).includes(code)) continue;
        taken = other;
        bindings[other.action] = codesOf(other).filter((existing) => existing !== code);
      }
      // The new key replaces the action's keyboard keys and keeps its pointer and stick codes.
      bindings[spec.action] = [code, ...codesOf(spec).filter((existing) => !isKey(existing))];
      store.set({ bindings });
      live.textContent = taken
        ? `${t("controlSet", { action: spec.label, key: keyName(code, t) })}. ${t("controlTaken", { key: keyName(code, t), action: taken.label })}`
        : t("controlSet", { action: spec.label, key: keyName(code, t) });
      refresh();
    };

    const rows = controls.map((spec) => {
      const button = el("button", { type: "button", class: "kg-btn", "aria-pressed": "false" });
      buttons.set(spec.action, button);
      button.addEventListener("click", () => {
        cancelCapture?.();
        button.setAttribute("aria-pressed", "true");
        button.textContent = t("controlPress");
        const finish = (): void => {
          document.removeEventListener("keydown", onKey, true);
          button.setAttribute("aria-pressed", "false");
          cancelCapture = null;
          refresh();
        };
        const onKey = (event: KeyboardEvent): void => {
          // The next key is the answer: it must reach neither the dialog nor the game.
          event.preventDefault();
          event.stopPropagation();
          if (event.key !== "Escape" && !event.repeat) assign(spec, event.code);
          if (!event.repeat) finish();
        };
        document.addEventListener("keydown", onKey, true);
        cancelCapture = finish;
      });
      return el("div", { class: "kg-row" }, button);
    });
    const reset = el("button", { type: "button", class: "kg-btn" }, t("controlsReset"));
    reset.addEventListener("click", () => {
      cancelCapture?.();
      store.set({ bindings: Object.fromEntries(controls.map((s) => [s.action, [...s.codes]])) });
      live.textContent = t("controlsWereReset");
      refresh();
    });
    refresh();
    sections.push(
      group(t("controlsHeading"), el("p", { class: "kg-hint" }, t("controlsHint")), ...rows, reset),
    );
  }

  const body = el("div", {}, ...sections, live);
  return ui.dialog({
    title: t("settingsTitle"),
    body,
    // The first control, so a tall dialog opens at its heading and not at its last button.
    initialFocus: body.querySelector<HTMLElement>("input") ?? undefined,
    actions: [{ id: "close", label: t("close"), primary: true }],
    onClose: () => {
      cancelCapture?.();
      store.flush();
      options.onClose?.();
    },
  });
}
