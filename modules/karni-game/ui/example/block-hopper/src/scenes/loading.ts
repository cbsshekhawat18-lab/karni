import type { Scene } from "@karni/game/scenes";
import type { ScreenHandle } from "@karni/game/ui";
import type { GameHooks, GameServices } from "./services";

export interface LoadingOptions {
  title: string;
  /** Does the work and reports how far it is, from 0 to 1. A throw reaches `onFailed`. */
  run(report: (fraction: number) => void): Promise<void>;
  onDone(): void;
  onFailed(error: unknown): void;
}

/**
 * A loading scene: a panel with a progress bar over the idle world. It takes
 * a `run` function, so it serves the first load and each stage's art alike.
 */
export function createLoadingScene(hooks: GameHooks, options: LoadingOptions): Scene<GameServices> {
  let screen: ScreenHandle | null = null;
  let live = true;
  return {
    name: "loading",
    enter({ services }) {
      const bar = document.createElement("progress");
      bar.className = "hopper-progress";
      bar.max = 100;
      bar.value = 0;
      bar.setAttribute("aria-label", options.title);
      screen = services.ui.screen({ title: options.title, actions: [] });
      screen.element.querySelector(".kg-body")?.append(bar);
      options
        .run((fraction) => {
          if (live) bar.value = Math.round(fraction * 100);
        })
        .then(
          () => live && options.onDone(),
          (error: unknown) => live && options.onFailed(error),
        );
    },
    exit() {
      live = false;
      screen?.close();
      screen = null;
    },
    draw: () => hooks.render(),
  };
}
