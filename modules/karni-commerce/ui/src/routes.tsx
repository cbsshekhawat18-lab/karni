/**
 * Where the commerce pages are, and how to go there. The components link to
 * the cart, checkout and orders through this, so they work with any router:
 * wrap the app once in `<CommerceProvider navigate={...}>` with the router's
 * push, and change a path with `paths`. Without a provider, links are plain
 * page loads to the default paths.
 */
import { createContext, useContext, useMemo, type MouseEvent, type ReactNode } from "react";

export interface CommercePaths {
  /** Where to browse for things to buy (an empty cart's link). */
  browse: string;
  cart: string;
  checkout: string;
  /** The signed-in person's orders. */
  orders: string;
  terms: string;
  /** One order's page. A guest reads it with its key. */
  order: (number: number | string, key?: string) => string;
  /** The sign-in page, coming back to `next`. */
  signIn: (next: string) => string;
  /** Staff: the customers list. */
  customers: string;
  /** Staff: one customer's page, by email (a project without the person page). */
  customer: (email: string) => string;
  /** Staff: one person's page (karni.people's `/people/<id>`), where a buyer links first. */
  person: (id: string) => string;
  /** Staff: an order placed by hand. */
  newOrder: string;
  /** An order's printable invoice. A guest reads it with its key. */
  invoice: (number: number | string, key?: string) => string;
  /** Staff: an order's packing slip. */
  packingSlip: (number: number | string) => string;
}

export const DEFAULT_COMMERCE_PATHS: CommercePaths = {
  browse: "/",
  cart: "/cart",
  checkout: "/checkout",
  orders: "/orders",
  terms: "/terms",
  order: (number, key) => `/orders/${number}${key ? `?key=${encodeURIComponent(key)}` : ""}`,
  signIn: (next) => `/signin?next=${encodeURIComponent(next)}`,
  customers: "/customers",
  customer: (email) => `/customers/${encodeURIComponent(email)}`,
  person: (id) => `/people/${encodeURIComponent(id)}`,
  newOrder: "/orders/new",
  invoice: (number, key) =>
    `/orders/${number}/invoice${key ? `?key=${encodeURIComponent(key)}` : ""}`,
  packingSlip: (number) => `/orders/${number}/packing-slip`,
};

export interface CommerceContextValue {
  paths: CommercePaths;
  navigate: (to: string) => void;
}

function pageLoad(to: string): void {
  window.location.assign(to);
}

const CommerceContext = createContext<CommerceContextValue>({
  paths: DEFAULT_COMMERCE_PATHS,
  navigate: pageLoad,
});

export interface CommerceProviderProps {
  /** The router's navigation (`(to) => router.history.push(to)`). Default: a page load. */
  navigate?: (to: string) => void;
  /** Paths that differ from the defaults. */
  paths?: Partial<CommercePaths>;
  children?: ReactNode;
}

let registered: Partial<CommercePaths> = {};

/**
 * Experimental. Paths a selling part sets once at startup, under the
 * provider's `paths`: the shop's catalogue is where an empty cart sends the
 * buyer (`registerCommercePaths({ browse: "/shop/catalogue" })`).
 */
export function registerCommercePaths(paths: Partial<CommercePaths>): void {
  registered = { ...registered, ...paths };
}

/** Experimental. The paths parts registered (tests, a project's own provider). */
export function registeredCommercePaths(): Partial<CommercePaths> {
  return registered;
}

export function CommerceProvider({ navigate, paths, children }: CommerceProviderProps) {
  const value = useMemo<CommerceContextValue>(
    () => ({
      paths: { ...DEFAULT_COMMERCE_PATHS, ...registered, ...paths },
      navigate: navigate ?? pageLoad,
    }),
    [navigate, paths],
  );
  return <CommerceContext.Provider value={value}>{children}</CommerceContext.Provider>;
}

/** The commerce paths and navigation in scope. */
export function useCommerce(): CommerceContextValue {
  return useContext(CommerceContext);
}

export interface CommerceLinkProps {
  to: string;
  className?: string;
  children?: ReactNode;
}

/** A link that navigates through the provider (a real `<a href>`, so it opens in a new tab too). */
export function CommerceLink({ to, className, children }: CommerceLinkProps) {
  const { navigate } = useCommerce();
  const follow = (event: MouseEvent<HTMLAnchorElement>) => {
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    navigate(to);
  };
  return (
    <a href={to} className={className} onClick={follow}>
      {children}
    </a>
  );
}
