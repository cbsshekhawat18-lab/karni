// The game's keys in one place: the input is made from them and Settings remaps them.
import { POINTER } from "@karni/game";
import type { ControlSpec, TouchButtonSpec } from "@karni/game/ui";

export const BINDINGS = {
    jump: ["Space", "ArrowUp", "KeyW", POINTER],
    pause: ["Escape", "KeyP"],
    mute: ["KeyM"],
} as const;

/** What a player may remap in Settings. */
export const CONTROLS: readonly ControlSpec[] = [
    { action: "jump", label: "Jump", codes: BINDINGS.jump },
    { action: "pause", label: "Pause", codes: BINDINGS.pause },
    { action: "mute", label: "Mute", codes: BINDINGS.mute },
];

/** On a touch screen: a tap anywhere jumps, and these two buttons sit under the thumbs. */
export const TOUCH_BUTTONS: readonly TouchButtonSpec[] = [
    { action: "pause", label: "Pause", side: "left" },
    { action: "jump", label: "Jump", side: "right" },
];
