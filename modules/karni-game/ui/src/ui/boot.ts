import { el, uid } from "./dom";
import { createTranslate, type Strings } from "./strings";
import { ensureStyles } from "./style";

export interface BootFailureOptions {
  /** What the player reads. Default: a plain sentence that it did not start. */
  title?: string;
  message?: string;
  /** The error: its message and stack go under "Details", for a bug report. */
  error?: unknown;
  /** What Try again does. Default: reload the page. */
  onRetry?(): void;
  strings?: Partial<Strings>;
  theme?: "auto" | "light" | "dark";
  /** Where the screen goes. Default `document.body`. */
  host?: HTMLElement;
}

export interface BootFailure {
  readonly element: HTMLElement;
  destroy(): void;
}

function describe(error: unknown): string {
  if (error instanceof Error)
    return error.stack ? `${error.message}\n${error.stack}` : error.message;
  return typeof error === "string" ? error : "";
}

/**
 * A screen the player can read when the game cannot start (no WebGL, a failed
 * load, a throw in boot), with a Try again button. It needs nothing else of
 * the kit, so it works when everything else did not.
 */
export function showBootFailure(options: BootFailureOptions = {}): BootFailure {
  const host = options.host ?? document.body;
  ensureStyles(host.ownerDocument);
  const t = createTranslate(options.strings);
  const titleId = uid("kg-boot");
  const detail = describe(options.error);
  const retry = el(
    "button",
    { type: "button", class: "kg-btn", "data-kg-primary": "" },
    t("retry"),
  );
  const element = el(
    "div",
    {
      class: "kg-ui kg-boot",
      role: "alert",
      "aria-labelledby": titleId,
      "data-kg-theme": options.theme ?? "auto",
    },
    el(
      "div",
      { class: "kg-boot-card" },
      el("h1", { id: titleId }, options.title ?? t("bootFailedTitle")),
      el("p", {}, options.message ?? t("bootFailedMessage")),
      detail ? el("details", {}, el("summary", {}, t("details")), el("pre", {}, detail)) : null,
      el("div", { class: "kg-actions" }, retry),
    ),
  );
  retry.addEventListener("click", () => {
    if (options.onRetry) options.onRetry();
    else window.location.reload();
  });
  host.appendChild(element);
  retry.focus();
  return { element, destroy: () => element.remove() };
}

/**
 * Run the game's start. If it throws, show the failure screen, and Try again
 * runs the start again. Resolves true when it started.
 */
export async function guardBoot(
  boot: () => void | Promise<void>,
  options: Omit<BootFailureOptions, "error"> = {},
): Promise<boolean> {
  try {
    await boot();
    return true;
  } catch (error) {
    const screen = showBootFailure({
      ...options,
      error,
      onRetry:
        options.onRetry ??
        (() => {
          screen.destroy();
          void guardBoot(boot, options);
        }),
    });
    return false;
  }
}
