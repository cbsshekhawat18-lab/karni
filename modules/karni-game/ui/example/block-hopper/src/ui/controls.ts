import { POINTER, STICK } from "@karni/game";
import type { ControlSpec, TouchButtonSpec } from "@karni/game/ui";

/** The bindings of the game, in one place: the input is created from them and Settings remaps them. */
export const BINDINGS = {
  left: ["ArrowLeft", "KeyA", STICK.left],
  right: ["ArrowRight", "KeyD", STICK.right],
  jump: ["Space", "ArrowUp", "KeyW", POINTER],
  pause: ["Escape", "KeyP"],
  mute: ["KeyM"],
  revive: ["KeyR"],
} as const;

/** The controls a player may remap in Settings. */
export const CONTROLS: readonly ControlSpec[] = [
  { action: "left", label: "Left", codes: BINDINGS.left },
  { action: "right", label: "Right", codes: BINDINGS.right },
  { action: "jump", label: "Jump", codes: BINDINGS.jump },
  { action: "pause", label: "Pause", codes: BINDINGS.pause },
  { action: "mute", label: "Mute", codes: BINDINGS.mute },
];

/** On-screen buttons for a touch screen: they press the same actions. */
export const TOUCH_BUTTONS: readonly TouchButtonSpec[] = [
  { action: "left", label: "Left", side: "left" },
  { action: "right", label: "Right", side: "left" },
  { action: "pause", label: "Pause", side: "right" },
  { action: "jump", label: "Jump", side: "right" },
];
