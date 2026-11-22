import type { Scene } from "@karni/game/scenes";
import type { TouchButtons } from "@karni/game/ui";
import { createTouchButtons } from "@karni/game/ui";
import { TOUCH_BUTTONS } from "../ui";
import { createPauseScene } from "./pause";
import type { GameHooks, GameServices } from "./services";

/** A run: the sim loop steps the rules after this scene's update, and Pause opens the pause overlay above it. */
export function createPlayScene(hooks: GameHooks): Scene<GameServices> {
  let buttons: TouchButtons | null = null;
  // A slow frame runs several steps with one key press in all of them: ask for the menu once.
  let asked = false;
  const addButtons = ({ ui, input }: GameServices): void => {
    if (input && !buttons) buttons = createTouchButtons(ui, input, TOUCH_BUTTONS);
  };
  const removeButtons = (): void => {
    buttons?.destroy();
    buttons = null;
  };
  return {
    name: "play",
    enter: ({ services }) => addButtons(services),
    exit: removeButtons,
    // The pause menu and the game-over panel cover the run: its buttons go while they are up.
    pause: removeButtons,
    resume: ({ services }) => {
      asked = false;
      addButtons(services);
    },
    update({ services, stack }, dt) {
      // Asked before the rules run: they clear the input's edge flags after a step.
      if (services.input?.pressed("pause") && stack.top?.name === "play" && !asked) {
        asked = true;
        stack.push(createPauseScene(hooks), { overlay: true });
        return;
      }
      hooks.update(dt);
    },
    draw: (_context, alpha) => hooks.render(alpha),
  };
}
