import type { Scene, SceneContext } from "@karni/game/scenes";
import type { ScreenHandle } from "@karni/game/ui";
import { TITLE } from "../game";
import { createShopScene } from "./shop";
import type { GameHooks, GameServices } from "./services";

/** The title: the bests, the coins, the daily run and the shop. Space or a tap anywhere starts a run. */
export function createTitleScene(hooks: GameHooks): Scene<GameServices> {
    let screen: ScreenHandle | null = null;
    const open = ({ services, stack }: SceneContext<GameServices>): void => {
        screen?.close();
        const session = services.run.session;
        const daily = session?.daily;
        const today = session?.dailyBest;
        const lines = [
            "Tap or press Space to jump, and again in the air to jump twice.",
            `Best ${session?.progress.best ?? 0}. Coins ${session?.coins() ?? 0}.`,
            daily
                ? today
                    ? `Today's run (${daily.date}): best ${today.best} in ${today.tries} ${today.tries === 1 ? "try" : "tries"}.`
                    : `Today's run (${daily.date}): the same track for every player.`
                : "",
        ];
        screen = services.ui.screen({
            title: TITLE,
            text: lines.filter(Boolean).join(" "),
            actions: [
                { id: "play", label: "Play", primary: true },
                { id: "daily", label: "Today's run" },
                { id: "shop", label: "Shop" },
                { id: "settings", label: "Settings" },
            ],
            onAction(id) {
                if (id === "play") services.run.begin("endless");
                else if (id === "daily") services.run.begin("daily");
                else if (id === "shop") stack.push(createShopScene(hooks), { overlay: true });
                else hooks.openSettings();
            },
        });
    };
    return {
        name: "title",
        enter: open,
        // Back from the shop: the coins and what the runner wears may have changed.
        resume: open,
        pause() {
            screen?.close();
            screen = null;
        },
        exit() {
            screen?.close();
            screen = null;
        },
        update: (_context, dt) => hooks.keys(dt),
        draw: (_context, alpha) => hooks.render(alpha),
    };
}
