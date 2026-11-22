import type { SceneServices, Store } from "@karni/game/scenes";
import type { Sfx } from "@karni/game/sfx";
import type { Settings, Ui } from "@karni/game/ui";
import type { RunControl } from "../run";

/** What every scene is handed: the package's services and the game's own. No scene imports a global. */
export interface GameServices extends SceneServices {
    ui: Ui;
    settings: Store<Settings>;
    sfx: Sfx;
    run: RunControl;
}

/** What the scenes call back into main.ts. */
export interface GameHooks {
    /** The menus' keys on every fixed step (mute, a jump that starts a run). */
    keys(dt: number): void;
    /** Draw the world: `alpha` is the leftover fraction of a fixed step. */
    render(alpha: number): void;
    openSettings(): void;
}
