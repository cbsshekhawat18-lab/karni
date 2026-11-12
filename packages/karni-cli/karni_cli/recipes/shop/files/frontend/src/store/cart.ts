// The cart: the signed-in customer's on the server, or a visitor's, found by the token
// this browser keeps. Signing in merges the visitor's cart into the customer's.
import { KarniApiError, useAuth, useKarniClient, useToast } from "@karni/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import type { Cart } from "./types";

const TOKEN_KEY = "shop.cart-token";
const CART_KEY = ["shop", "cart"] as const;

function readToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function writeToken(token: string | null): void {
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    // storage is off (a private window): the cart lasts for this page only
  }
}

function headers(): Record<string, string> {
  const token = readToken();
  return token ? { "X-Cart-Token": token } : {};
}

/** The plain words of an API error: the first field message, else the detail. */
export function problemOf(error: unknown): string {
  if (
    error instanceof KarniApiError &&
    error.data &&
    typeof error.data === "object"
  ) {
    for (const value of Object.values(error.data as Record<string, unknown>)) {
      if (Array.isArray(value) && typeof value[0] === "string") return value[0];
      if (typeof value === "string") return value;
    }
  }
  return error instanceof Error
    ? error.message
    : "Something went wrong. Try again.";
}

/** The shopper's cart, kept fresh across pages. */
export function useCart() {
  const client = useKarniClient();
  const { status, user } = useAuth();
  return useQuery<Cart>({
    queryKey: [
      ...CART_KEY,
      status === "authenticated" ? (user?.id ?? null) : null,
    ],
    enabled: status !== "loading",
    queryFn: ({ signal }) =>
      client.request<Cart>("/carts/current/", { headers: headers(), signal }),
  });
}

/** Put a quantity of a product in the cart (0 takes it out). */
export function useSetQuantity() {
  const client = useKarniClient();
  const queries = useQueryClient();
  const { error } = useToast();
  return useMutation({
    mutationFn: (input: { product: string; quantity: number }) =>
      client.request<Cart>("/carts/current/items/", {
        method: "POST",
        body: input,
        headers: headers(),
      }),
    onSuccess: (cart) => {
      if (cart.token) writeToken(cart.token);
      void queries.invalidateQueries({ queryKey: CART_KEY });
    },
    onError: (problem) =>
      error("The cart did not change", { description: problemOf(problem) }),
  });
}

/** Once someone signs in, the cart this browser kept as a visitor joins theirs. */
export function useMergeOnSignIn(): void {
  const client = useKarniClient();
  const queries = useQueryClient();
  const { status } = useAuth();
  const merged = useRef(false);
  useEffect(() => {
    if (status !== "authenticated") {
      merged.current = false;
      return;
    }
    if (merged.current) return;
    merged.current = true;
    const token = readToken() ?? "";
    void client
      .request<Cart>("/carts/current/merge/", {
        method: "POST",
        body: { token },
      })
      .then(() => {
        writeToken(null);
        void queries.invalidateQueries({ queryKey: CART_KEY });
        void queries.invalidateQueries({ queryKey: ["karni", "orders"] });
      })
      .catch(() => {
        merged.current = false;
      });
  }, [client, queries, status]);
}

/** Forget the visitor's cart and refresh: checkout emptied it. */
export function useCartPlaced(): () => void {
  const queries = useQueryClient();
  return () => void queries.invalidateQueries({ queryKey: CART_KEY });
}

export { headers as cartHeaders };
