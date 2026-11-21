import type { Input } from "../input/input";
import { el, focusables, uid } from "./dom";
import { createTranslate, type Strings, type Translate } from "./strings";
import { ensureStyles } from "./style";

export interface DialogAction {
  id: string;
  label: string;
  /** The main choice: styled as such and focused first. */
  primary?: boolean;
  /** A choice that destroys something. */
  danger?: boolean;
  /** Run `onAction` and leave the dialog open (a "Settings" button on a pause menu). */
  keepOpen?: boolean;
}

export interface DialogOptions {
  title: string;
  /** Text, or any element (the settings dialog builds its own). */
  body?: string | Node;
  /** Default: one "OK". */
  actions?: DialogAction[];
  /** Escape and a click outside close it, resolving null. Default true. */
  dismissable?: boolean;
  /** The action to focus first. Default: the primary action, else the first control. */
  initialFocus?: string;
  /** `alertdialog` for a question that needs an answer. Default `dialog`. */
  role?: "dialog" | "alertdialog";
  /** Called for every action. The dialog closes after it unless the action has `keepOpen`. */
  onAction?(id: string, dialog: DialogHandle): void;
  /** Called once when it closes, with the action id or null. */
  onClose?(result: string | null): void;
}

export interface DialogHandle {
  readonly element: HTMLElement;
  /** Resolves with the id of the action chosen, or null when it was dismissed. */
  readonly result: Promise<string | null>;
  readonly open: boolean;
  close(result?: string | null): void;
}

export interface ScreenOptions {
  title: string;
  text?: string;
  actions: DialogAction[];
  /** Where the panel sits. Default "center". */
  align?: "center" | "bottom";
  /** Focus the primary action when it shows, so Enter and Space work at once. Default true. */
  autoFocus?: boolean;
  onAction?(id: string, screen: ScreenHandle): void;
}

export interface ScreenHandle {
  readonly element: HTMLElement;
  close(): void;
}

export interface ConfirmOptions {
  title: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Style the confirm button as destructive. */
  danger?: boolean;
}

export interface ToastOptions {
  kind?: "info" | "success" | "error";
  /** How long it stays, in ms. 0 keeps it until dismissed. Default 4000, 8000 for an error. */
  durationMs?: number;
}

export interface UiOptions {
  /** The element the layer covers. Default `document.body` (the layer is then fixed to the window). */
  host?: HTMLElement;
  /** Replace any of the kit's words. */
  strings?: Partial<Strings>;
  /** "auto" follows the system. Default "auto". */
  theme?: "auto" | "light" | "dark";
  /** Let go of held keys when a dialog opens, so nothing sticks while it is up. */
  input?: Pick<Input, "releaseAll">;
  /** Make the stylesheet. Default true. Set false to ship your own CSS for the `kg-` classes. */
  styles?: boolean;
}

/** The DOM layer above the canvas. */
export interface Ui {
  /** The layer: a positioned element over the host. */
  readonly root: HTMLElement;
  /** The place for screens and buttons that sit under dialogs. */
  readonly hud: HTMLElement;
  readonly t: Translate;
  /** A dialog that traps focus, closes on Escape and gives focus back. */
  dialog(options: DialogOptions): DialogHandle;
  /** Ask yes or no. Resolves false when dismissed. */
  confirm(options: ConfirmOptions): Promise<boolean>;
  /** A panel of choices that is part of the page (a title screen). The canvas behind it still gets taps. */
  screen(options: ScreenOptions): ScreenHandle;
  /** A short message, announced to screen readers. */
  toast(message: string, options?: ToastOptions): { close(): void };
  /** A dialog is open. */
  readonly modal: boolean;
  setTheme(theme: "auto" | "light" | "dark"): void;
  setPalette(palette: "default" | "safe"): void;
  setReducedMotion(reduced: boolean): void;
  /** Close every dialog and toast, remove the layer. */
  destroy(): void;
}

function makeButton(action: DialogAction, run: (id: string) => void): HTMLButtonElement {
  const button = el(
    "button",
    { type: "button", class: "kg-btn", "data-kg-action": action.id },
    action.label,
  );
  if (action.primary) button.setAttribute("data-kg-primary", "");
  if (action.danger) button.setAttribute("data-kg-danger", "");
  button.addEventListener("click", () => run(action.id));
  return button;
}

/**
 * Make the DOM layer: dialogs, confirm, screens and toasts above the canvas.
 * It is plain elements, so the browser lays out text, moves focus and reads
 * it aloud. A React game mounts it by passing a ref's element as `host`.
 */
export function createUi(options: UiOptions = {}): Ui {
  const host = options.host ?? document.body;
  if (options.styles !== false) ensureStyles(host.ownerDocument);
  const t = createTranslate(options.strings);

  const root = el("div", { class: "kg-ui kg-root", "data-kg-theme": options.theme ?? "auto" });
  if (host === document.body) root.setAttribute("data-kg-fixed", "");
  const hud = el("div", { class: "kg-hud" });
  const toasts = el("div", {
    class: "kg-toasts",
    role: "region",
    "aria-label": t("notifications"),
  });
  root.append(hud, toasts);
  host.appendChild(root);

  interface Modal {
    element: HTMLElement;
    handle: DialogHandle;
    restore: Element | null;
  }
  const modals: Modal[] = [];
  const timers = new Set<ReturnType<typeof setTimeout>>();

  const refreshInert = (): void => {
    const top = modals[modals.length - 1]?.element;
    for (const child of root.children) {
      if (child === toasts) continue;
      child.toggleAttribute("inert", modals.length > 0 && child !== top);
    }
  };

  const dialog = (dialogOptions: DialogOptions): DialogHandle => {
    const dismissable = dialogOptions.dismissable ?? true;
    const titleId = uid("kg-title");
    const actions = dialogOptions.actions ?? [{ id: "ok", label: t("ok"), primary: true }];
    let resolve: (value: string | null) => void = () => undefined;
    const result = new Promise<string | null>((done) => {
      resolve = done;
    });
    let isOpen = true;

    const body =
      typeof dialogOptions.body === "string"
        ? el("p", {}, dialogOptions.body)
        : (dialogOptions.body ?? null);
    const actionsRow = el("div", { class: "kg-actions" });
    const panel = el(
      "div",
      {
        class: "kg-dialog",
        role: dialogOptions.role ?? "dialog",
        "aria-modal": "true",
        "aria-labelledby": titleId,
        tabindex: "-1",
      },
      el("h2", { id: titleId }, dialogOptions.title),
      body,
      actions.length > 0 ? actionsRow : null,
    );
    const element = el("div", { class: "kg-modal" }, panel);

    const handle: DialogHandle = {
      element: panel,
      result,
      get open() {
        return isOpen;
      },
      close(value = null) {
        if (!isOpen) return;
        isOpen = false;
        const at = modals.findIndex((modal) => modal.element === element);
        const [gone] = at >= 0 ? modals.splice(at, 1) : [];
        element.remove();
        refreshInert();
        const wasTop = at === modals.length;
        if (wasTop && gone?.restore instanceof HTMLElement && gone.restore.isConnected) {
          gone.restore.focus();
        }
        resolve(value);
        dialogOptions.onClose?.(value);
      },
    };

    for (const action of actions) {
      actionsRow.append(
        makeButton(action, (id) => {
          dialogOptions.onAction?.(id, handle);
          if (!action.keepOpen) handle.close(id);
        }),
      );
    }

    element.addEventListener("keydown", (event) => {
      // Keys typed in a dialog never reach the game's input.
      event.stopPropagation();
      if (event.key === "Escape" && dismissable) {
        event.preventDefault();
        handle.close(null);
      } else if (event.key === "Tab") {
        const reachable = focusables(panel);
        const first = reachable[0];
        const last = reachable[reachable.length - 1];
        if (!first || !last) {
          event.preventDefault();
          panel.focus();
        } else if (
          event.shiftKey &&
          (document.activeElement === first || document.activeElement === panel)
        ) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    });
    element.addEventListener("keyup", (event) => event.stopPropagation());
    if (dismissable) {
      element.addEventListener("pointerdown", (event) => {
        if (event.target === element) handle.close(null);
      });
    }

    options.input?.releaseAll();
    modals.push({ element, handle, restore: document.activeElement });
    root.appendChild(element);
    refreshInert();
    const wanted =
      (dialogOptions.initialFocus &&
        actionsRow.querySelector<HTMLElement>(
          `[data-kg-action="${dialogOptions.initialFocus}"]`,
        )) ||
      actionsRow.querySelector<HTMLElement>("[data-kg-primary]") ||
      focusables(panel)[0] ||
      panel;
    wanted.focus();
    return handle;
  };

  const ui: Ui = {
    root,
    hud,
    t,
    dialog,
    async confirm(confirmOptions) {
      const answer = await dialog({
        title: confirmOptions.title,
        body: confirmOptions.message,
        role: "alertdialog",
        actions: [
          { id: "cancel", label: confirmOptions.cancelLabel ?? t("cancel") },
          {
            id: "confirm",
            label: confirmOptions.confirmLabel ?? t("ok"),
            primary: !confirmOptions.danger,
            danger: confirmOptions.danger,
          },
        ],
        // A destructive question starts on the safe answer.
        initialFocus: confirmOptions.danger ? "cancel" : "confirm",
      }).result;
      return answer === "confirm";
    },
    screen(screenOptions) {
      const titleId = uid("kg-title");
      const actions = el("div", { class: "kg-actions" });
      const section = el(
        "section",
        { class: "kg-screen", "aria-labelledby": titleId, "data-kg-align": screenOptions.align },
        el(
          "div",
          { class: "kg-panel" },
          el("h2", { id: titleId }, screenOptions.title),
          screenOptions.text ? el("p", {}, screenOptions.text) : null,
          actions,
        ),
      );
      const handle: ScreenHandle = {
        element: section,
        close: () => section.remove(),
      };
      for (const action of screenOptions.actions) {
        actions.append(makeButton(action, (id) => screenOptions.onAction?.(id, handle)));
      }
      // Enter and Space press the focused button and do nothing else in the game.
      section.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") event.stopPropagation();
      });
      hud.appendChild(section);
      if (screenOptions.autoFocus !== false) {
        actions.querySelector<HTMLElement>("[data-kg-primary], button")?.focus();
      }
      return handle;
    },
    toast(message, toastOptions = {}) {
      const kind = toastOptions.kind ?? "info";
      const text = el("span", { class: "kg-toast-text" }, message);
      const dismiss = el("button", { type: "button", class: "kg-btn" }, t("dismiss"));
      const toast = el(
        "div",
        { class: "kg-toast", role: kind === "error" ? "alert" : "status", "data-kg-kind": kind },
        text,
        dismiss,
      );
      let timer: ReturnType<typeof setTimeout> | null = null;
      const close = (): void => {
        if (timer !== null) {
          clearTimeout(timer);
          timers.delete(timer);
        }
        toast.remove();
      };
      dismiss.addEventListener("click", close);
      toasts.appendChild(toast);
      while (toasts.children.length > 3) toasts.firstElementChild?.remove();
      const duration = toastOptions.durationMs ?? (kind === "error" ? 8000 : 4000);
      if (duration > 0) {
        timer = setTimeout(close, duration);
        timers.add(timer);
      }
      return { close };
    },
    get modal() {
      return modals.length > 0;
    },
    setTheme: (theme) => root.setAttribute("data-kg-theme", theme),
    setPalette: (palette) => {
      if (palette === "safe") root.setAttribute("data-kg-palette", "safe");
      else root.removeAttribute("data-kg-palette");
    },
    setReducedMotion: (reduced) => {
      if (reduced) root.setAttribute("data-kg-motion", "reduced");
      else root.removeAttribute("data-kg-motion");
    },
    destroy() {
      for (const modal of [...modals]) modal.handle.close(null);
      for (const timer of timers) clearTimeout(timer);
      timers.clear();
      root.remove();
    },
  };
  return ui;
}
