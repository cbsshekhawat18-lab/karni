import { createSceneStack } from "@karni/game/scenes";
import { createLoadingScene, type LoadingOptions } from "./loading";
import { createOverScene, type RunResult } from "./over";
import { createPlayScene } from "./play";
import type { GameHooks, GameServices } from "./services";
import { createTitleScene } from "./title";

export type { RunResult } from "./over";
export type { GameHooks, GameServices } from "./services";

export type ScreenName = "title" | "play";
export type { LoadingOptions } from "./loading";

/**
 * Block Hopper's scenes on the scene stack: loading, a title, a play scene,
 * and the pause and game-over overlays above it. The rules live in src/rules
 * on @karni/game/sim, the sim loop and the canvas drawing stay in main.ts,
 * and scenes reach them through `hooks`, so a scene imports no global.
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
    /**
     * Replace what is on screen with a loading scene (the game-over panel goes
     * first). `onDone` or `onFailed` runs when `run` ends.
     */
    load(options: LoadingOptions): void {
      const scene = createLoadingScene(hooks, options);
      if (stack.top?.name === "over") stack.pop();
      if (stack.depth === 0) stack.push(scene);
      else stack.replace(scene, { duration: 0.2 });
    },
    /** Show the scene for the game's screen. */
    go(screen: ScreenName): void {
      if (screen === "title" && !stack.has("title")) {
        stack.clear();
        stack.push(createTitleScene(hooks));
      } else if (screen === "play" && stack.top?.name === "over") {
        // Hop again or continue: the play scene is still below.
        stack.pop();
      } else if (screen === "play" && !stack.has("play")) {
        const scene = createPlayScene(hooks);
        if (stack.depth === 0) stack.push(scene);
        else stack.replace(scene, { duration: 0.3 });
      }
    },
    /** The run ended: the game-over panel over the world where it ended. */
    over(result: RunResult): void {
      if (!stack.has("over")) stack.push(createOverScene(hooks, result), { overlay: true });
    },
  };
}
