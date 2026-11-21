import type { Input } from "../input/input";
import { el } from "./dom";
import type { Ui } from "./ui";

export interface TouchButtonSpec {
  /** The action or key code pressed on the input while the button is held. */
  action: string;
  /** The button's text and its name for a screen reader. */
  label: string;
  /** Which corner it sits in. Default "right". */
  side?: "left" | "right";
}

export interface TouchButtonsOptions {
  /**
   * "touch" shows the buttons on touch screens: a coarse pointer, or at the
   * first touch. "always" and "never" force it. Default "touch".
   */
  show?: "touch" | "always" | "never";
}

export interface TouchButtons {
  readonly element: HTMLElement;
  show(visible: boolean): void;
  destroy(): void;
}

/**
 * On-screen buttons that press the input's actions, so one binding serves
 * the keyboard, the stick and the screen. Real buttons: a screen reader
 * names them and Enter and Space press them.
 */
export function createTouchButtons(
  ui: Pick<Ui, "hud" | "t">,
  input: Pick<Input, "press" | "release">,
  buttons: readonly TouchButtonSpec[],
  options: TouchButtonsOptions = {},
): TouchButtons {
  const mode = options.show ?? "touch";
  const left = el("div", { class: "kg-touch-group" });
  const right = el("div", { class: "kg-touch-group" });
  const element = el("div", { class: "kg-touch", role: "group" }, left, right);
  element.setAttribute("aria-label", ui.t("touchControls"));
  if (mode === "always") element.setAttribute("data-kg-show", "");
  if (mode === "never") element.setAttribute("data-kg-hide", "");

  const cleanups: (() => void)[] = [];
  for (const spec of buttons) {
    const button = el(
      "button",
      { type: "button", class: "kg-btn", "data-kg-touch": spec.action },
      spec.label,
    );
    let down = false;
    const press = (): void => {
      if (down) return;
      down = true;
      button.setAttribute("data-kg-down", "");
      input.press(spec.action);
    };
    const release = (): void => {
      if (!down) return;
      down = false;
      button.removeAttribute("data-kg-down");
      input.release(spec.action);
    };
    button.addEventListener("pointerdown", (event) => {
      // The canvas and the window never see a press that belongs to a button.
      event.stopPropagation();
      event.preventDefault();
      try {
        button.setPointerCapture(event.pointerId);
      } catch {
        // A synthetic pointer cannot be captured.
      }
      press();
    });
    for (const type of ["pointerup", "pointercancel", "lostpointercapture"] as const) {
      button.addEventListener(type, release);
    }
    button.addEventListener("contextmenu", (event) => event.preventDefault());
    button.addEventListener("blur", release);
    button.addEventListener("keydown", (event) => {
      event.stopPropagation();
      if ((event.key === "Enter" || event.key === " ") && !event.repeat) {
        event.preventDefault();
        press();
      }
    });
    button.addEventListener("keyup", (event) => {
      event.stopPropagation();
      if (event.key === "Enter" || event.key === " ") release();
    });
    (spec.side === "left" ? left : right).append(button);
    cleanups.push(release);
  }

  const reveal = (event: PointerEvent): void => {
    if (event.pointerType === "touch") element.setAttribute("data-kg-show", "");
  };
  if (mode === "touch") window.addEventListener("pointerdown", reveal, true);

  ui.hud.appendChild(element);
  return {
    element,
    show(visible) {
      element.toggleAttribute("data-kg-show", visible);
      element.toggleAttribute("data-kg-hide", !visible);
    },
    destroy() {
      for (const release of cleanups) release();
      window.removeEventListener("pointerdown", reveal, true);
      element.remove();
    },
  };
}
