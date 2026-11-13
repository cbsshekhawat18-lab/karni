// The storefront's frame: a header with the shop's name, the products, the account and
// the mini cart, the page, and a footer. Phones get the same links in rows that wrap.
import { MiniCart, useBusiness, useMergeOnSignIn } from "@karni/commerce-ui";
import { Button, ThemeToggle, useAuth } from "@karni/ui";
import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { useIsStaff } from "./staff";

// The shop's name before the settings arrive: index.html's title, which karni new set to
// the project's name. Settings, Details changes it (useShopName).
export const SHOP_NAME =
  typeof document === "undefined" ? "Shop" : document.title || "Shop";

/** The shop's name as Settings, Details has it, else the project's name. */
export function useShopName(): string {
  const business = useBusiness();
  return business.data?.name || SHOP_NAME;
}

function Account() {
  const { status, logout } = useAuth();
  const staff = useIsStaff();
  if (status !== "authenticated") {
    return (
      <Link to="/signin" className="text-sm font-medium hover:underline">
        Sign in
      </Link>
    );
  }
  return (
    <span className="flex flex-wrap items-center gap-3 text-sm">
      {staff ? (
        <Link to="/" className="font-medium hover:underline">
          Back office
        </Link>
      ) : null}
      <Link to="/orders" className="font-medium hover:underline">
        My orders
      </Link>
      <Link to="/shop/wishlist" className="font-medium hover:underline">
        Wishlist
      </Link>
      <Link to="/account" className="font-medium hover:underline">
        Account
      </Link>
      <Button variant="ghost" onClick={() => void logout()}>
        Sign out
      </Button>
    </span>
  );
}

export function StoreLayout({ children }: { children: ReactNode }) {
  useMergeOnSignIn();
  const name = useShopName();
  const business = useBusiness().data;
  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <a href="#main" className="sr-only focus:not-sr-only focus:p-2">
        Skip to content
      </a>
      <header className="border-b border-border bg-card">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <Link
            to="/shop"
            className="flex items-center gap-2 text-lg font-semibold"
          >
            <span
              aria-hidden="true"
              className="h-6 w-6 rounded-md bg-primary"
            />
            {name}
          </Link>
          <nav aria-label="Shop" className="flex gap-4 text-sm font-medium">
            <Link to="/shop/catalogue" className="hover:underline">
              Products
            </Link>
          </nav>
          <div className="ml-auto flex flex-wrap items-center gap-3">
            <Account />
            <MiniCart />
            <ThemeToggle />
          </div>
        </div>
      </header>
      <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
        {children}
      </main>
      <footer className="border-t border-border">
        <div className="mx-auto flex max-w-6xl flex-wrap gap-4 px-4 py-6 text-sm text-muted-foreground">
          <span className="font-medium text-foreground">{name}</span>
          {business?.address ? (
            <span className="whitespace-pre-line">{business.address}</span>
          ) : null}
          {business?.phone ? <span>{business.phone}</span> : null}
          {business?.email ? (
            <a href={`mailto:${business.email}`} className="hover:underline">
              {business.email}
            </a>
          ) : null}
          <Link to="/shop/terms" className="hover:underline">
            Terms
          </Link>
          <Link to="/orders" className="hover:underline">
            Your orders
          </Link>
        </div>
      </footer>
    </div>
  );
}
