// The storefront's frame: a header with the shop's name, the products, the account and
// the mini cart, the page, and a footer. Phones get the same links in rows that wrap.
import { MiniCart, useMergeOnSignIn } from "@karni/commerce-ui";
import { Button, ThemeToggle, useAuth } from "@karni/ui";
import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { useIsStaff } from "./staff";

// The shop's name: index.html's title, which karni new set to the project's name.
export const SHOP_NAME =
  typeof document === "undefined" ? "Shop" : document.title || "Shop";

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
            {SHOP_NAME}
          </Link>
          <nav aria-label="Shop" className="flex gap-4 text-sm font-medium">
            <Link to="/shop/products" className="hover:underline">
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
          <span>{SHOP_NAME}</span>
          <Link to="/terms" className="hover:underline">
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
