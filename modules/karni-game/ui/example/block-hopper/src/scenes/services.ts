import type { SceneServices } from "@karni/game/scenes";
import type { Settings, Ui } from "@karni/game/ui";
import type { Store } from "@karni/game/scenes";

/** What every scene of Block Hopper is handed: the package's services and the game's own. */
export interface GameServices extends SceneServices {
  ui: Ui;
  settings: Store<Settings>;
}

/** What the scenes call back into the game's rules and canvas code. */
export interface GameHooks {
  update(dt: number): void;
  render(): void;
  start(): void;
  toTitle(): void;
}
