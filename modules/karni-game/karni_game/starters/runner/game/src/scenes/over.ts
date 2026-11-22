import type { Scene, SceneContext } from "@karni/game/scenes";
import type { DialogAction, ScreenHandle } from "@karni/game/ui";
import type { RunResult } from "../run";
import { createShopScene } from "./shop";
import type { GameHooks, GameServices } from "./services";

/** Keys wait this long after a crash, so the jump that came too late does not start a new run. */
const SETTLE = 0.6;

/**
 * Game over: a panel at the foot of the screen with the run's score, the top of its board
 * when it arrives, and what next. An overlay: the track stands still behind it.
 */
export function createOverScene(hooks: GameHooks, result: RunResult): Scene<GameServices> {
    let panel: ScreenHandle | null = null;
    let waited = 0;
    const open = ({ services, stack }: SceneContext<GameServices>): void => {
        panel?.close();
        const actions: DialogAction[] = [{ id: "again", label: "Run again", primary: true }];
        if (result.canContinue) actions.push({ id: "continue", label: "Watch an ad to continue" });
        actions.push({ id: "shop", label: "Shop" }, { id: "title", label: "Title" });
        const daily = result.mode === "daily";
        const opened = services.ui.screen({
            title: daily ? "Today's run is over" : "Run over",
            text: `${result.score} points: ${result.distance} m and ${result.coins} ${result.coins === 1 ? "coin" : "coins"}. Best ${result.best}.`,
            align: "bottom",
            actions,
            onAction(id) {
                if (id === "again") services.run.begin(result.mode);
                else if (id === "continue") {
                    void services.run.continueRun().then((granted) => {
                        if (!granted) services.ui.toast("No ad to watch right now. Try again in a moment.");
                    });
                } else if (id === "shop") stack.push(createShopScene(hooks), { overlay: true });
                else services.run.show("title");
            },
        });
        panel = opened;
        opened.element.querySelector(".kg-panel")?.classList.add("sd-compact");
        void result.board.then((entries) => {
            if (panel !== opened || entries.length === 0) return;
            const list = document.createElement("ol");
            list.className = "sd-list sd-board";
            list.setAttribute("aria-label", daily ? "Today's board" : "Distance board");
            for (const entry of entries.slice(0, 5)) {
                const item = document.createElement("li");
                item.textContent = `${entry.rank}. ${entry.handle}: ${entry.value}${entry.me ? " (you)" : ""}`;
                list.append(item);
            }
            opened.element.querySelector(".kg-actions")?.before(list);
        });
    };
    return {
        name: "over",
        overlay: true,
        enter: open,
        resume: open,
        pause() {
            panel?.close();
            panel = null;
        },
        exit() {
            panel?.close();
            panel = null;
        },
        update({ services }, dt) {
            waited += dt;
            if (waited < SETTLE) {
                services.input?.endFrame();
                return;
            }
            if (services.input?.pressed("jump")) services.run.begin(result.mode);
            else hooks.keys(dt);
        },
        draw: () => undefined,
    };
}
