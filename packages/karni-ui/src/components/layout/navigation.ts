/**
 * Experimental. The server's menu (`useNavigation`) as Layout entries: links
 * and collapsible groups, icons by name, the current page marked.
 *
 * The current page is the item whose route is the path, else the item with
 * the longest route the path is under (`/products/42` is under `/products`),
 * so exactly one item is marked even when routes nest. `/` is marked only
 * on `/`.
 *
 * Escape hatch: Layout's `navSource="server"` calls it for you. Call it
 * yourself to change the entries before they render, or build `navItems`
 * by hand.
 */
import type * as React from "react";
import type { NavigationItem } from "../../hooks/useNavigation";
import type { LayoutNavEntry } from "./layout";
import { navIcon } from "./nav-icons";

/** Experimental. What `navigationEntries` needs besides the items. */
export interface NavigationEntriesOptions {
  /** The current location's path: marks the current page. */
  pathname: string;
  /** Icons by name, over `defaultNavIcons`. */
  icons?: Readonly<Record<string, React.ReactNode>>;
}

function normal(path: string): string {
  const bare = path.split("?")[0]?.split("#")[0] ?? "";
  return bare.replace(/\/+$/, "") || "/";
}

function routes(items: readonly NavigationItem[]): string[] {
  return items.flatMap((item) =>
    item.route !== null ? [normal(item.route)] : routes(item.children),
  );
}

/** Experimental. The route of the current page among `items`, or null: exact first, then the longest prefix. */
export function activeRoute(items: readonly NavigationItem[], pathname: string): string | null {
  const here = normal(pathname);
  const all = routes(items);
  if (all.includes(here)) return here;
  let best: string | null = null;
  for (const route of all) {
    if (
      route !== "/" &&
      here.startsWith(`${route}/`) &&
      (best === null || route.length > best.length)
    ) {
      best = route;
    }
  }
  return best;
}

/** Experimental. Layout entries for the server's menu, with the current page marked. */
export function navigationEntries(
  items: readonly NavigationItem[],
  options: NavigationEntriesOptions,
): LayoutNavEntry[] {
  const current = activeRoute(items, options.pathname);
  const build = (level: readonly NavigationItem[], trail: string): LayoutNavEntry[] =>
    level.map((item, index) => {
      const key = `${trail}${index}`;
      if (item.route === null) {
        return {
          key: `group:${key}`,
          label: item.label,
          icon: navIcon(item.icon, options.icons),
          children: build(item.children, `${key}.`),
        };
      }
      return {
        key: `item:${key}`,
        href: item.route,
        label: item.label,
        icon: navIcon(item.icon, options.icons),
        active: current !== null && normal(item.route) === current,
      };
    });
  return build(items, "");
}
