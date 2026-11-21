import type { Scene } from "@karni/game/scenes";
import { openPause, type DialogHandle } from "@karni/game/ui";
import type { GameHooks, GameServices } from "./services";

/** The pause overlay: the run stands still below, the loop is paused (the sound with it). */
export function createPauseScene(hooks: GameHooks): Scene<GameServices> {
    let menu: DialogHandle | null = null;
    return {
        name: "pause",
        overlay: true,
        enter({ services, stack }) {
            menu = openPause(services.ui, {
                loop: services.loop,
                onSettings: () => hooks.openSettings(),
                onResume: () => stack.pop(),
                onQuit: () => services.run.show("title"),
            });
        },
        exit() {
            menu?.close();
            menu = null;
        },
        draw: () => undefined,
    };
}
