import type { SceneServices } from "@karni/game/scenes";
import type { Settings, Ui } from "@karni/game/ui";
import type { Store } from "@karni/game/scenes";

/** What every scene of Block Hopper is handed: the package's services and the game's own. */
export interface GameServices extends SceneServices {
  ui: Ui;
  settings: Store<Settings>;
}

/** What the scenes call back into the game's own code in main.ts. */
export interface GameHooks {
  /** The game's keys on every fixed step: start, continue, mute. The sim loop runs the rules after it. */
  update(dt: number): void;
  /** Draw the world: `alpha` is the leftover fraction of a fixed step. */
  render(alpha: number): void;
  start(): void;
  /** Watch a rewarded ad and, when it pays, go on with the run. */
  continueRun(): void;
  toTitle(): void;
}
