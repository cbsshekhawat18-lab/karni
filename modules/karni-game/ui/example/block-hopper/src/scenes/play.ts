import type { Scene } from "@karni/game/scenes";
import type { TouchButtons } from "@karni/game/ui";
import { createTouchButtons } from "@karni/game/ui";
import { TOUCH_BUTTONS } from "../ui";
import { createPauseScene } from "./pause";
import type { GameHooks, GameServices } from "./services";

/** A run: the rules advance here, and Pause opens the pause overlay above it. */
export function createPlayScene(hooks: GameHooks): Scene<GameServices> {
  let buttons: TouchButtons | null = null;
  return {
    name: "play",
    enter({ services }) {
      if (services.input) buttons = createTouchButtons(services.ui, services.input, TOUCH_BUTTONS);
    },
    exit() {
      buttons?.destroy();
      buttons = null;
    },
    update({ services, stack }, dt) {
      // Asked before the rules run: they clear the input's edge flags after a step.
      if (services.input?.pressed("pause") && stack.top?.name === "play") {
        stack.push(createPauseScene(hooks), { overlay: true });
        return;
      }
      hooks.update(dt);
    },
    draw: () => hooks.render(),
  };
}
