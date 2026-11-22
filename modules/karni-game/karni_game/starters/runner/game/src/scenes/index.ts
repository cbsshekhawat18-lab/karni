import { createSceneStack } from "@karni/game/scenes";
import type { RunResult, Screen } from "../run";
import { createLoadingScene, type LoadingOptions } from "./loading";
import { createOverScene } from "./over";
import { createPlayScene } from "./play";
import type { GameHooks, GameServices } from "./services";
import { createTitleScene } from "./title";

export type { GameHooks, GameServices } from "./services";
export type { LoadingOptions } from "./loading";

/**
 * The game's scenes on the scene stack: loading, the title, a run, and the pause, game-over
 * and shop overlays above them. The rules live in src/rules, the run in src/run.ts and the
 * drawing in src/art: scenes reach them through their services and hooks.
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
        get cover(): number {
            return stack.cover;
        },
        load(options: LoadingOptions): void {
            stack.clear();
            stack.push(createLoadingScene(hooks, options));
        },
        /** Show the scene for a screen of the run. */
        go(screen: Screen): void {
            if (screen === "title" && stack.top?.name !== "title") {
                stack.clear();
                stack.push(createTitleScene(hooks));
            } else if (screen === "play") {
                // Run again or a continue: the play scene is still below the game-over panel.
                if (stack.top?.name === "over") stack.pop();
                else if (!stack.has("play")) {
                    stack.clear();
                    stack.push(createPlayScene(hooks));
                }
            }
        },
        over(result: RunResult): void {
            if (!stack.has("over")) stack.push(createOverScene(hooks, result), { overlay: true });
        },
    };
}
