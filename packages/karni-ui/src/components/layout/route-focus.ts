/**
 * Layout's focus management after a client-side navigation, the way
 * accessible SPA routers do it: once the new page is in, focus moves to its
 * main heading (else <main>) and a polite live region says its title.
 *
 * It needs no router. The route is the URL's path (a hash route such as
 * `#/events` included, search params left out), or the `routeKey` option. A
 * change is noticed when the Layout renders and when anything in <main>
 * changes, so a router that re-renders only its outlet is covered too.
 * Internal to @karni/ui. Layout's `routeFocus` prop is the public surface.
 */
import * as React from "react";

/** What Layout's `routeFocus` prop takes when it is an object. */
export interface LayoutRouteFocusOptions {
  /**
   * The current route: focus moves when it changes. Default: the URL's path
   * (`location.pathname`, plus a hash route such as `#/events`), so a change
   * of search params only (filters, pagination, sorting) never moves focus.
   * Pass your router's pathname or route id when the URL does not say which
   * page is showing (a memory router).
   */
  routeKey?: string;
  /**
   * The element that takes focus after a navigation. Default: the first
   * `<h1>` in `<main>`, else `<main>` itself. An element that cannot take
   * focus gets `tabindex="-1"`.
   */
  getTarget?: (main: HTMLElement) => HTMLElement | null;
  /**
   * What the live region says after a navigation. Default: the document
   * title when the new page changed it, else the heading's text. Return ""
   * to say nothing.
   */
  getAnnouncement?: (target: HTMLElement) => string;
}

interface Settled {
  key: string;
  heading: HTMLElement | null;
  text: string;
  title: string;
}

function locationKey(): string {
  const { pathname, hash } = window.location;
  // A hash router keeps its route in the hash: its path counts, its query does not.
  const hashRoute = hash.startsWith("#/") || hash.startsWith("#!/") ? hash.split("?")[0] : "";
  return `${pathname}${hashRoute}`;
}

function defaultTarget(main: HTMLElement): HTMLElement | null {
  return main.querySelector<HTMLElement>("h1");
}

function textOf(element: HTMLElement | null): string {
  return element?.textContent?.trim() ?? "";
}

const FIELD_SELECTOR = 'input, textarea, select, [contenteditable=""], [contenteditable="true"]';

/**
 * Whether something already took focus for the new page, which the Layout
 * then leaves alone: a control inside <main> (an autofocused field, a link
 * of the page that is still there), an open dialog, or a form field anywhere
 * (a search box in the header that navigates as you type).
 */
function focusClaimed(main: HTMLElement, target: HTMLElement): boolean {
  const active = document.activeElement;
  if (!(active instanceof HTMLElement)) return false;
  if (active === document.body || active === main || active === target) return false;
  if (active.closest('[role="dialog"], [role="alertdialog"], dialog') !== null) return true;
  if (active.closest(FIELD_SELECTOR) !== null) return true;
  return main.contains(active);
}

function defaultAnnouncement(target: HTMLElement, main: HTMLElement, before: Settled): string {
  const title = document.title.trim();
  if (title !== "" && title !== before.title) return title;
  const heading = target === main ? "" : textOf(target);
  return heading !== "" ? heading : title;
}

export interface RouteFocusOptions extends LayoutRouteFocusOptions {
  enabled: boolean;
}

/** What counts as the user acting: a key, a pointer, or Back and Forward. */
const INTERACTIONS = ["keydown", "pointerdown", "popstate"] as const;

/**
 * Watches the route and, after a navigation, moves focus into the new page.
 * Returns the live region's text.
 */
export function useRouteFocus(
  mainRef: React.RefObject<HTMLElement | null>,
  options: RouteFocusOptions,
): string {
  const { enabled } = options;
  const [announcement, setAnnouncement] = React.useState("");
  // The callbacks are read when they run, so inline functions do not re-subscribe.
  const latest = React.useRef(options);
  latest.current = options;
  const settled = React.useRef<Settled | null>(null);
  const pending = React.useRef<{ key: string; mutated: boolean } | null>(null);
  const timer = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  // Redirects before the user does anything ("/" to "/dashboard") are part of the first load.
  const interacted = React.useRef(false);

  const snapshot = React.useCallback((key: string, main: HTMLElement): Settled => {
    const heading = (latest.current.getTarget ?? defaultTarget)(main);
    return { key, heading, text: textOf(heading), title: document.title.trim() };
  }, []);

  const finish = React.useCallback((): void => {
    timer.current = null;
    const main = mainRef.current;
    const navigation = pending.current;
    const before = settled.current;
    if (main === null || navigation === null || before === null) return;
    const { getTarget, getAnnouncement } = latest.current;
    const target = (getTarget ?? defaultTarget)(main) ?? main;
    // The old page is still up (the router waits for data): the next change in <main> ends the wait.
    const sameHeading = target === before.heading && textOf(target) === before.text;
    if (!navigation.mutated && sameHeading) return;
    pending.current = null;
    if (!focusClaimed(main, target)) {
      if (target.tabIndex < 0 && !target.hasAttribute("tabindex")) {
        target.setAttribute("tabindex", "-1");
      }
      // The router owns scrolling (top of the page, or where Back left it).
      target.focus({ preventScroll: true });
    }
    setAnnouncement(
      getAnnouncement !== undefined
        ? getAnnouncement(target)
        : defaultAnnouncement(target, main, before),
    );
    settled.current = snapshot(navigation.key, main);
  }, [mainRef, snapshot]);

  const check = React.useCallback(
    (mutated: boolean): void => {
      const main = mainRef.current;
      if (main === null) return;
      const key = latest.current.routeKey ?? locationKey();
      const before = settled.current;
      if (before === null || !interacted.current) {
        // The first load: the browser already put focus where it belongs.
        settled.current = snapshot(key, main);
        return;
      }
      if (key === before.key) {
        // The same page (a search-param change, new data): only keep up with it.
        if (pending.current !== null) {
          pending.current = null;
          if (timer.current !== null) clearTimeout(timer.current);
          timer.current = null;
        }
        settled.current = snapshot(key, main);
        return;
      }
      if (pending.current?.key !== key) {
        pending.current = { key, mutated: false };
        setAnnouncement("");
      }
      if (mutated) pending.current.mutated = true;
      // After the page's own effects: an autofocused field wins, and the title is set.
      if (timer.current !== null) clearTimeout(timer.current);
      timer.current = setTimeout(finish, 0);
    },
    [mainRef, snapshot, finish],
  );

  React.useEffect(() => {
    if (!enabled || interacted.current) return undefined;
    const stop = (): void => {
      for (const name of INTERACTIONS) window.removeEventListener(name, mark, true);
    };
    const mark = (): void => {
      interacted.current = true;
      stop();
    };
    for (const name of INTERACTIONS) window.addEventListener(name, mark, true);
    return stop;
  }, [enabled]);

  React.useEffect(() => {
    const main = mainRef.current;
    if (!enabled || main === null) return undefined;
    const observer = new MutationObserver(() => check(true));
    observer.observe(main, { childList: true, subtree: true, characterData: true });
    return () => {
      observer.disconnect();
      if (timer.current !== null) clearTimeout(timer.current);
      timer.current = null;
    };
  }, [enabled, mainRef, check]);

  // Every render: the Layout re-renders when its router's location changes.
  React.useEffect(() => {
    if (enabled) check(false);
  });

  React.useEffect(() => {
    if (enabled) return;
    // Switched off: the next time it is on starts from that page, as on a first load.
    settled.current = null;
    pending.current = null;
  }, [enabled]);

  return enabled ? announcement : "";
}
