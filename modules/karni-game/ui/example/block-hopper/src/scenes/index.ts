import { createSceneStack } from "@karni/game/scenes";
import { createPlayScene } from "./play";
import type { GameHooks, GameServices } from "./services";
import { createTitleScene } from "./title";

export type { GameHooks, GameServices } from "./services";

export type ScreenName = "title" | "play" | "over";

/**
 * Block Hopper's scenes on the scene stack: a title, a play scene and a pause
 * overlay. The rules and the canvas drawing stay in main.ts and are reached
 * through `hooks`, so a scene imports no global.
 */
export function createGameScenes(services: GameServices, hooks: GameHooks) {
  const stack = createSceneStack<GameServices>({
    services,
    reducedMotion: () => services.settings.state.reducedMotion,
  });
  return {
    stack,
    update: (dt: number): void => stack.update(dt),
    draw: (alpha: number): void => stack.draw(alpha),
    /** How covered the screen is while a scene change fades. */
    get cover(): number {
      return stack.cover;
    },
    /** Show the scene for the game's screen. "over" stays on the play scene. */
    go(screen: ScreenName): void {
      if (screen === "title" && !stack.has("title")) {
        stack.clear();
        stack.push(createTitleScene(hooks));
      } else if (screen === "play" && !stack.has("play")) {
        const scene = createPlayScene(hooks);
        if (stack.depth === 0) stack.push(scene);
        else stack.replace(scene, { duration: 0.3 });
      }
    },
  };
}
