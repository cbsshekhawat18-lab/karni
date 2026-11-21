import type { Loop } from "../runtime/loop";
import type { DialogAction, DialogHandle, Ui } from "./ui";

export interface PauseOptions {
  /** Paused with the reason "menu" while the menu is open, so audio and the game stand still. */
  loop?: Pick<Loop, "pause" | "resume">;
  /** Show a Settings button that calls this. The menu stays open behind it. */
  onSettings?(): void;
  /** Show a Quit button. It asks first unless `confirmQuit` is false. */
  onQuit?(): void;
  /** Ask "Quit the game?" before `onQuit`. Default true. */
  confirmQuit?: boolean;
  /** Called when the menu closes by Resume or Escape. */
  onResume?(): void;
}

/** The pause menu: Resume, Settings and Quit. It pauses the loop while it is open. */
export function openPause(ui: Ui, options: PauseOptions = {}): DialogHandle {
  const { t } = ui;
  const actions: DialogAction[] = [{ id: "resume", label: t("resume"), primary: true }];
  if (options.onSettings) actions.push({ id: "settings", label: t("settings"), keepOpen: true });
  if (options.onQuit) actions.push({ id: "quit", label: t("quit"), keepOpen: true });
  options.loop?.pause("menu");
  return ui.dialog({
    title: t("pauseTitle"),
    actions,
    initialFocus: "resume",
    onAction(id, dialog) {
      if (id === "settings") options.onSettings?.();
      if (id === "quit") {
        const quit = (): void => {
          dialog.close("quit");
          options.onQuit?.();
        };
        if (options.confirmQuit === false) quit();
        else {
          void ui
            .confirm({
              title: t("quitTitle"),
              message: t("quitMessage"),
              confirmLabel: t("quit"),
              danger: true,
            })
            .then((yes) => {
              if (yes) quit();
            });
        }
      }
    },
    onClose(result) {
      options.loop?.resume("menu");
      if (result !== "quit") options.onResume?.();
    },
  });
}
