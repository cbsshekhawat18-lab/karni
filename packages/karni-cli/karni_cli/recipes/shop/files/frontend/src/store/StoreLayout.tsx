// The storefront's frame: a header with the shop's name, the catalogue, the account and the
// mini cart, the page, and a footer. Phones get the same links in one row that wraps.
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  ThemeToggle,
  useAuth,
} from "@karni/ui";
import { Link, useRouter } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { useCart, useMergeOnSignIn } from "./cart";
import { Money } from "./Price";
import { BACK_OFFICE, useIsStaff } from "./staff";

// The shop's name: index.html's title, which karni new set to the project's name.
export const SHOP_NAME =
  typeof document === "undefined" ? "Shop" : document.title || "Shop";

function MiniCart() {
  const router = useRouter();
  const cart = useCart().data;
  const count = cart?.count ?? 0;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          aria-label={`Cart, ${count} ${count === 1 ? "item" : "items"}`}
        >
          Cart{" "}
          <span className="ml-1 rounded-full bg-primary px-2 text-xs text-primary-foreground">
            {count}
          </span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72">
        <DropdownMenuLabel>
          {count === 0 ? "Your cart is empty" : "In your cart"}
        </DropdownMenuLabel>
        {(cart?.lines ?? []).slice(0, 5).map((line) => (
          <DropdownMenuItem
            key={line.id}
            onSelect={() => router.history.push(`/shop/${line.product.slug}`)}
          >
            <span className="flex w-full justify-between gap-2">
              <span className="truncate">
                {line.quantity} x {line.product.name}
              </span>
              <Money value={line.line_total} />
            </span>
          </DropdownMenuItem>
        ))}
        {count > 0 ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuLabel className="flex justify-between">
              Subtotal <Money value={cart?.subtotal ?? "0"} />
            </DropdownMenuLabel>
            <DropdownMenuItem onSelect={() => router.history.push("/cart")}>
              View the cart
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => router.history.push("/checkout")}>
              Check out
            </DropdownMenuItem>
          </>
        ) : (
          <DropdownMenuItem onSelect={() => router.history.push("/shop")}>
            Browse the shop
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
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
        <Link to={BACK_OFFICE} className="font-medium hover:underline">
          Back office
        </Link>
      ) : null}
      <Link to="/account" className="font-medium hover:underline">
        My orders
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
            to="/"
            className="flex items-center gap-2 text-lg font-semibold"
          >
            <span
              aria-hidden="true"
              className="h-6 w-6 rounded-md bg-primary"
            />
            {SHOP_NAME}
          </Link>
          <nav aria-label="Shop" className="flex gap-4 text-sm font-medium">
            <Link to="/shop" className="hover:underline">
              Shop
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
          <Link to="/account" className="hover:underline">
            Your account
          </Link>
        </div>
      </footer>
    </div>
  );
}
