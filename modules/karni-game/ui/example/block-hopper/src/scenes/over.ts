import type { BoardEntry } from "@karni/game";
import type { Scene } from "@karni/game/scenes";
import type { DialogAction, ScreenHandle } from "@karni/game/ui";
import type { GameHooks, GameServices } from "./services";

/** What the game-over panel shows. The board arrives after the score is sent. */
export interface RunResult {
  score: number;
  best: number;
  /** The rewarded continue is still open for this run. */
  canContinue: boolean;
  board: Promise<readonly BoardEntry[]>;
}

/**
 * Game over: a panel at the foot of the screen with the score, the board and
 * the next step, so nothing is drawn over the block where the run ended. It
 * is an overlay: the world below stays drawn and stands still, and this
 * scene's update reads the game's keys (Space or a tap to hop again, R to
 * continue).
 */
export function createOverScene(hooks: GameHooks, result: RunResult): Scene<GameServices> {
  let panel: ScreenHandle | null = null;
  return {
    name: "over",
    overlay: true,
    enter({ services }) {
      const actions: DialogAction[] = [{ id: "again", label: "Hop again", primary: true }];
      if (result.canContinue) actions.push({ id: "continue", label: "Watch an ad to continue" });
      const opened = services.ui.screen({
        title: "Fell!",
        text: `Score ${result.score}. Best ${result.best}.`,
        align: "bottom",
        actions,
        onAction: (id) => (id === "continue" ? hooks.continueRun() : hooks.start()),
      });
      panel = opened;
      void result.board.then((entries) => {
        if (panel !== opened || entries.length === 0) return;
        const list = document.createElement("ol");
        list.className = "board";
        list.setAttribute("aria-label", "Leaderboard");
        for (const entry of entries) {
          const item = document.createElement("li");
          item.textContent = `${entry.rank}. ${entry.handle} ${entry.value}`;
          list.append(item);
        }
        opened.element.querySelector(".kg-actions")?.before(list);
      });
    },
    exit() {
      panel?.close();
      panel = null;
    },
    update: (_context, dt) => hooks.update(dt),
    draw: () => undefined,
  };
}
