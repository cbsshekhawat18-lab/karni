import type { Scene } from "@karni/game/scenes";
import type { ScreenHandle } from "@karni/game/ui";
import { openGameSettings } from "../ui";
import type { GameHooks, GameServices } from "./services";

/** The title: a DOM panel over the idle world. A tap or Space anywhere still starts a run. */
export function createTitleScene(hooks: GameHooks): Scene<GameServices> {
  let screen: ScreenHandle | null = null;
  return {
    name: "title",
    enter({ services }) {
      screen = services.ui.screen({
        title: "Block Hopper",
        text: "Arrows or the stick to move, Space or a tap to jump.",
        actions: [
          { id: "play", label: "Play", primary: true },
          { id: "settings", label: "Settings" },
        ],
        onAction(id) {
          if (id === "play") hooks.start();
          else openGameSettings(services);
        },
      });
    },
    exit() {
      screen?.close();
      screen = null;
    },
    // The rules' own update reads the jump that starts a run, and the mute key.
    update: (_context, dt) => hooks.update(dt),
    draw: () => hooks.render(),
  };
}
