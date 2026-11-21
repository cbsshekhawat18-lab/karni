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

/** A panel with a progress bar over the idle sky, while the session opens. */
export function createLoadingScene(hooks: GameHooks, options: LoadingOptions): Scene<GameServices> {
    let screen: ScreenHandle | null = null;
    let live = true;
    return {
        name: "loading",
        enter({ services }) {
            const bar = document.createElement("progress");
            bar.className = "sd-progress";
            bar.max = 100;
            bar.value = 0;
            bar.setAttribute("aria-label", "Loading");
            screen = services.ui.screen({ title: options.title, text: "Getting ready.", actions: [] });
            screen.element.querySelector(".kg-panel h2")?.after(bar);
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
        draw: (_context, alpha) => hooks.render(alpha),
    };
}
