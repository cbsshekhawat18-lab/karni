import type { Scene } from "@karni/game/scenes";
import { openPause, type DialogHandle } from "@karni/game/ui";
import { openGameSettings } from "../ui";
import type { GameHooks, GameServices } from "./services";

/**
 * The pause overlay: the run below is drawn and stands still, the loop is
 * paused for the reason "menu" (audio follows it), and Resume, Escape or
 * Quit to the title leave it.
 */
export function createPauseScene(hooks: GameHooks): Scene<GameServices> {
  let menu: DialogHandle | null = null;
  return {
    name: "pause",
    overlay: true,
    enter({ services, stack }) {
      menu = openPause(services.ui, {
        loop: services.loop,
        onSettings: () => openGameSettings(services),
        onResume: () => stack.pop(),
        onQuit: () => hooks.toTitle(),
      });
    },
    exit() {
      menu?.close();
      menu = null;
    },
    draw: () => undefined,
  };
}
