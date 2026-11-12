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
}

export const DEFAULT_COMMERCE_PATHS: CommercePaths = {
  browse: "/",
  cart: "/cart",
  checkout: "/checkout",
  orders: "/orders",
  terms: "/terms",
  order: (number, key) => `/orders/${number}${key ? `?key=${encodeURIComponent(key)}` : ""}`,
  signIn: (next) => `/signin?next=${encodeURIComponent(next)}`,
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

export function CommerceProvider({ navigate, paths, children }: CommerceProviderProps) {
  const value = useMemo<CommerceContextValue>(
    () => ({
      paths: { ...DEFAULT_COMMERCE_PATHS, ...paths },
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
