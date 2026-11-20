/**
 * Experimental. Carts with items that nobody touched for a while
 * (`GET /carts/abandoned/`), so the shop can write to the people it has an
 * email for. How long counts as a while is a setting of the shop.
 */
import {
  EmptyState,
  ErrorState,
  Input,
  Page,
  Skeleton,
  useKarniClient,
  usePageMeta,
} from "@karni/ui";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Money } from "./Money";
import type { AbandonedCart } from "./types";

interface Paged<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface AbandonedCartsPageProps {
  title?: string;
  siteName?: string;
}

export function AbandonedCartsPage({
  title = "Abandoned carts",
  siteName,
}: AbandonedCartsPageProps) {
  const client = useKarniClient();
  const [typed, setTyped] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  usePageMeta({ title, siteName });
  useEffect(() => {
    const wait = setTimeout(() => {
      setSearch(typed.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(wait);
  }, [typed]);
  const carts = useQuery<Paged<AbandonedCart>>({
    queryKey: ["karni-commerce", "abandoned", search, page],
    placeholderData: keepPreviousData,
    queryFn: ({ signal }) =>
      client.request<Paged<AbandonedCart>>("/carts/abandoned/", {
        query: { search, page },
        signal,
      }),
  });
  return (
    <Page title={title}>
      <p className="text-sm text-muted-foreground">
        Carts with items that nobody touched for a while (Settings, Checkout). Write to the people
        you have an email for.
      </p>
      <div className="space-y-1">
        <label htmlFor="abandoned-search" className="text-sm font-medium">
          Search
        </label>
        <Input
          id="abandoned-search"
          type="search"
          placeholder="Name or email"
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
          className="w-72 max-w-full"
        />
      </div>
      {carts.isPending ? (
        <Skeleton className="h-64 w-full" />
      ) : carts.isError ? (
        <ErrorState error={carts.error} onRetry={() => void carts.refetch()} />
      ) : carts.data.results.length === 0 ? (
        <EmptyState
          title={
            search
              ? "No cart matches"
              : "No abandoned carts: every cart either checked out or is still being filled."
          }
        />
      ) : (
        <>
          <div className="max-w-full overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-sm">
              <caption className="sr-only">{title}</caption>
              <thead className="bg-muted text-left text-muted-foreground">
                <tr>
                  <th scope="col" className="p-3 font-medium">
                    Who
                  </th>
                  <th scope="col" className="p-3 font-medium">
                    What
                  </th>
                  <th scope="col" className="p-3 text-right font-medium">
                    Items
                  </th>
                  <th scope="col" className="p-3 text-right font-medium">
                    Value
                  </th>
                  <th scope="col" className="p-3 font-medium">
                    Coupon
                  </th>
                  <th scope="col" className="p-3 font-medium">
                    Last touched
                  </th>
                </tr>
              </thead>
              <tbody>
                {carts.data.results.map((cart) => (
                  <tr key={cart.id} className="border-t border-border align-top">
                    <td className="p-3">
                      {cart.email ? (
                        <>
                          <span className="font-medium">{cart.name || cart.email}</span>
                          {cart.name ? (
                            <span className="block text-xs text-muted-foreground">
                              {cart.email}
                            </span>
                          ) : null}
                        </>
                      ) : (
                        <span className="font-medium">A visitor (no email yet)</span>
                      )}
                      <span className="block text-xs text-muted-foreground">
                        {cart.signed_in ? "Signed in" : "Visitor"}
                      </span>
                    </td>
                    <td className="p-3">
                      <ul>
                        {cart.lines.map((line, index) => (
                          <li key={index}>{line}</li>
                        ))}
                      </ul>
                    </td>
                    <td className="p-3 text-right tabular-nums">{cart.items}</td>
                    <td className="p-3 text-right tabular-nums">
                      <Money value={cart.value} currency={cart.currency} />
                    </td>
                    <td className="p-3">{cart.coupon}</td>
                    <td className="whitespace-nowrap p-3">
                      {new Date(cart.touched_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <nav aria-label="Pages" className="flex items-center justify-between gap-2 text-sm">
            <span>{carts.data.count} carts</span>
            <span className="flex gap-2">
              <button
                type="button"
                className="rounded-md border border-border px-3 py-1 disabled:opacity-50"
                disabled={!carts.data.previous}
                onClick={() => setPage(page - 1)}
              >
                Previous
              </button>
              <button
                type="button"
                className="rounded-md border border-border px-3 py-1 disabled:opacity-50"
                disabled={!carts.data.next}
                onClick={() => setPage(page + 1)}
              >
                Next
              </button>
            </span>
          </nav>
        </>
      )}
    </Page>
  );
}
