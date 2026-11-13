/**
 * The cart: the signed-in person's on the server, or a visitor's, found by
 * the token this browser keeps. Signing in merges the visitor's cart into
 * the person's (`useMergeOnSignIn`, once in the layout).
 */
import { KarniApiError, useAuth, useKarniClient, useToast } from "@karni/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import type { Address, Cart, Quote } from "./types";

/** Where this browser keeps a visitor's cart token. */
export const CART_TOKEN_KEY = "karni.cart-token";
/** The query key of the cart (invalidate it after a change made elsewhere). */
export const CART_QUERY_KEY = ["karni-commerce", "cart"] as const;
/** The header the API reads a visitor's cart token from. */
export const CART_TOKEN_HEADER = "X-Cart-Token";

export function readCartToken(): string | null {
  try {
    return window.localStorage.getItem(CART_TOKEN_KEY);
  } catch {
    return null;
  }
}

export function writeCartToken(token: string | null): void {
  try {
    if (token) window.localStorage.setItem(CART_TOKEN_KEY, token);
    else window.localStorage.removeItem(CART_TOKEN_KEY);
  } catch {
    // storage is off (a private window): the cart lasts for this page only
  }
}

/** The header that names this browser's visitor cart, when it has one. */
export function cartHeaders(): Record<string, string> {
  const token = readCartToken();
  return token ? { [CART_TOKEN_HEADER]: token } : {};
}

/** The plain words of an API error: the first field message, else the detail. */
export function problemOf(error: unknown): string {
  if (error instanceof KarniApiError && error.data && typeof error.data === "object") {
    for (const value of Object.values(error.data as Record<string, unknown>)) {
      if (Array.isArray(value) && typeof value[0] === "string") return value[0];
      if (typeof value === "string") return value;
      if (value && typeof value === "object") {
        for (const inner of Object.values(value as Record<string, unknown>)) {
          if (Array.isArray(inner) && typeof inner[0] === "string") return inner[0];
        }
      }
    }
  }
  return error instanceof Error ? error.message : "Something went wrong. Try again.";
}

/** The shopper's cart, kept fresh across pages. */
export function useCart() {
  const client = useKarniClient();
  const { status, user } = useAuth();
  return useQuery<Cart>({
    queryKey: [...CART_QUERY_KEY, status === "authenticated" ? (user?.id ?? null) : null],
    enabled: status !== "loading",
    queryFn: ({ signal }) =>
      client.request<Cart>("/carts/current/", { headers: cartHeaders(), signal }),
  });
}

/** The project's currency, as the cart reports it ("" until the cart loads). */
export function useCurrency(): string {
  return useCart().data?.currency ?? "";
}

export interface SetLineInput {
  kind: string;
  item: string;
  quantity: number;
  options?: Record<string, unknown>;
  /** Add to what the cart holds instead of setting it. */
  add?: boolean;
}

/** Put a quantity of an item in the cart (0 takes it out). */
export function useSetLine(options: { quiet?: boolean } = {}) {
  const client = useKarniClient();
  const queries = useQueryClient();
  const { error } = useToast();
  return useMutation({
    mutationFn: (input: SetLineInput) =>
      client.request<Cart>("/carts/current/lines/", {
        method: "POST",
        body: { options: {}, add: false, ...input },
        headers: cartHeaders(),
      }),
    onSuccess: (cart) => {
      if (cart.token) writeCartToken(cart.token);
      void queries.invalidateQueries({ queryKey: CART_QUERY_KEY });
    },
    onError: (problem) => {
      if (!options.quiet) error("The cart did not change", { description: problemOf(problem) });
    },
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
    const token = readCartToken() ?? "";
    void client
      .request<Cart>("/carts/current/merge/", { method: "POST", body: { token } })
      .then(() => {
        writeCartToken(null);
        void queries.invalidateQueries({ queryKey: CART_QUERY_KEY });
        void queries.invalidateQueries({ queryKey: ["karni", "orders"] });
      })
      .catch(() => {
        merged.current = false;
      });
  }, [client, queries, status]);
}

/** Put a coupon on the cart (a blank code takes it off). The error says why a code was refused. */
export function useApplyCoupon() {
  const client = useKarniClient();
  const queries = useQueryClient();
  return useMutation({
    mutationFn: (code: string) =>
      client.request<Cart>("/carts/current/coupon/", {
        method: "POST",
        body: { code },
        headers: cartHeaders(),
      }),
    onSuccess: (cart) => {
      if (cart.token) writeCartToken(cart.token);
      void queries.invalidateQueries({ queryKey: CART_QUERY_KEY });
    },
  });
}

/** Where the order goes, as far as the quote needs it. */
export type QuotePlace = Pick<Address, "country"> & Partial<Pick<Address, "region" | "postcode">>;

/**
 * What the cart comes to at `place` with the shipping method `method`: the ways
 * to send it, the tax and the total. Asked again when the cart, the place or
 * the method changes.
 */
export function useQuote(place: QuotePlace, method: string | null, email = "") {
  const client = useKarniClient();
  const cart = useCart();
  const country = place.country.toUpperCase();
  return useQuery<Quote>({
    queryKey: [
      ...CART_QUERY_KEY,
      "quote",
      cart.dataUpdatedAt,
      country,
      place.region ?? "",
      place.postcode ?? "",
      method ?? "",
      email,
    ],
    enabled: cart.isSuccess,
    placeholderData: (previous) => previous,
    queryFn: ({ signal }) =>
      client.request<Quote>("/carts/current/quote/", {
        method: "POST",
        headers: cartHeaders(),
        body: {
          address: { country, region: place.region ?? "", postcode: place.postcode ?? "" },
          shipping_method: method ?? "",
          email,
        },
        signal,
      }),
  });
}
