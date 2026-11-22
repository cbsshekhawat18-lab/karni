import { openSettings, type DialogHandle } from "@karni/game/ui";
import type { GameServices } from "../scenes/services";
import { CONTROLS } from "./controls";

export { BINDINGS, CONTROLS, TOUCH_BUTTONS } from "./controls";

/** The settings dialog of Block Hopper: volumes, mute, motion, palette and its remappable controls. */
export function openGameSettings({ ui, settings }: GameServices): DialogHandle {
  return openSettings(ui, { store: settings, controls: CONTROLS });
}
