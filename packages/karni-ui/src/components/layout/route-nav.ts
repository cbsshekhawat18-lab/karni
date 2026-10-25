/**
 * The staff app's menu from its routes: one entry per static route, in the
 * order the routes are registered.
 *
 * The scaffold's layout.tsx (and every app built on it) passes its router's
 * route paths here. Routes with a parameter (`/orders/$id`) and "new" forms
 * are reached from their list page, so they are left out, and the sign-in
 * page leaves the menu once someone is signed in.
 *
 * Escape hatch: every rule is an option (`label`, `hidden`, `signIn`), and a
 * layout may build its `navItems` by hand instead.
 */
import type { LayoutNavItem } from "./layout";

export interface RouteNavOptions {
  /** The current location's path: marks the active entry. */
  pathname: string;
  /** Someone is signed in: the sign-in routes leave the menu. Default false. */
  signedIn?: boolean;
  /** The text of a route's entry. Default: its last path segment, humanised ("Home" for `/`). */
  label?: (path: string) => string;
  /** Leave a route out. Default: routes with a `$param` and paths ending in `/new`. */
  hidden?: (path: string) => boolean;
  /** Sign-in routes: listed only while nobody is signed in. Default: {@link isSignInRoute}. */
  signIn?: (path: string) => boolean;
}

/** A sign-in page: a path whose last segment is `login` or `sign-in` (`/login`, `/staff/login`). */
export function isSignInRoute(path: string): boolean {
  const last = path.replace(/\/+$/, "").split("/").at(-1) ?? "";
  return last === "login" || last === "sign-in" || last === "signin";
}

/** `/orders/line-items` → "Line items", `/` → "Home". */
export function routeLabel(path: string): string {
  const name = path.split("/").filter(Boolean).at(-1) ?? "home";
  return name.replace(/[-_]+/g, " ").replace(/^./, (first) => first.toUpperCase());
}

function defaultHidden(path: string): boolean {
  return path.includes("$") || path.endsWith("/new");
}

/** Whether `pathname` is `path` or a page under it (`/orders/42` is under `/orders`). */
function isActive(path: string, pathname: string): boolean {
  if (path === pathname) return true;
  return path !== "/" && pathname.startsWith(`${path.replace(/\/+$/, "")}/`);
}

/**
 * Layout `navItems` for a router's route paths (TanStack Router:
 * `Object.keys(router.routesByPath)`), with the active one marked.
 */
export function routeNavItems(paths: Iterable<string>, options: RouteNavOptions): LayoutNavItem[] {
  const {
    pathname,
    signedIn = false,
    label = routeLabel,
    hidden = defaultHidden,
    signIn = isSignInRoute,
  } = options;
  const items: LayoutNavItem[] = [];
  const seen = new Set<string>();
  for (const path of paths) {
    if (seen.has(path) || hidden(path) || (signedIn && signIn(path))) continue;
    seen.add(path);
    items.push({ href: path, label: label(path), active: isActive(path, pathname) });
  }
  return items;
}
