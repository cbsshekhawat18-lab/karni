/**
 * The staff's customers: the people who bought (karni.people),
 * one row per person with commerce's facts (their orders, what they spent,
 * their last order), and one customer's page with their orders, addresses
 * and account.
 *
 * They read `GET /api/orders/customers/` and `GET /api/orders/customer/`
 * (karni_commerce.people). One person is the same record in every part, so a
 * name changed in the CRM shows here too.
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
import { CommerceLink, useCommerce } from "./routes";
import { ORDER_STATUS_WORDS } from "./status";
import type { Address, CustomerPageData, CustomerRow } from "./types";

interface Paged<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

const SORTS = [
  { value: "-last_order", label: "Latest order" },
  { value: "-spent", label: "Spent most" },
  { value: "-orders", label: "Most orders" },
  { value: "name", label: "Name" },
] as const;

export interface CustomersPageProps {
  title?: string;
  pageSize?: number;
}

export function CustomersPage({ title = "Customers", pageSize = 25 }: CustomersPageProps) {
  const client = useKarniClient();
  const { paths } = useCommerce();
  const [typed, setTyped] = useState("");
  const [search, setSearch] = useState("");
  const [ordering, setOrdering] = useState<string>("-last_order");
  const [page, setPage] = useState(1);
  useEffect(() => {
    const wait = setTimeout(() => {
      setSearch(typed.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(wait);
  }, [typed]);
  const rows = useQuery<Paged<CustomerRow>>({
    queryKey: ["karni-commerce", "customers", search, ordering, page, pageSize],
    placeholderData: keepPreviousData,
    queryFn: ({ signal }) =>
      client.request<Paged<CustomerRow>>("/orders/customers/", {
        query: { search, ordering, page, page_size: pageSize },
        signal,
      }),
  });
  const pages = rows.data ? Math.max(1, Math.ceil(rows.data.count / pageSize)) : 1;
  return (
    <Page title={title}>
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <label htmlFor="customer-search" className="text-sm font-medium">
            Search
          </label>
          <Input
            id="customer-search"
            type="search"
            placeholder="Name, email or order number"
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            className="w-72 max-w-full"
          />
        </div>
        <div className="space-y-1">
          <label htmlFor="customer-sort" className="text-sm font-medium">
            Sort by
          </label>
          <select
            id="customer-sort"
            className="h-10 rounded-md border border-input bg-background px-3 text-sm"
            value={ordering}
            onChange={(event) => {
              setOrdering(event.target.value);
              setPage(1);
            }}
          >
            {SORTS.map((sort) => (
              <option key={sort.value} value={sort.value}>
                {sort.label}
              </option>
            ))}
          </select>
        </div>
      </div>
      {rows.isPending ? (
        <Skeleton className="h-64 w-full" />
      ) : rows.isError ? (
        <ErrorState error={rows.error} onRetry={() => void rows.refetch()} />
      ) : rows.data.results.length === 0 ? (
        <EmptyState
          title={search ? "No customer matches" : "No customers yet"}
          description={
            search ? "Try another name or email." : "Customers appear with their first order."
          }
        />
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-sm">
              <caption className="sr-only">{title}</caption>
              <thead className="bg-muted text-left text-muted-foreground">
                <tr>
                  <th scope="col" className="p-3 font-medium">
                    Customer
                  </th>
                  <th scope="col" className="p-3 font-medium">
                    Orders
                  </th>
                  <th scope="col" className="p-3 text-right font-medium">
                    Spent
                  </th>
                  <th scope="col" className="p-3 font-medium">
                    Last order
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.data.results.map((row) => (
                  <tr key={row.id} className="border-t border-border">
                    <td className="p-3">
                      <CommerceLink
                        to={paths.customer(row.email)}
                        className="font-medium hover:underline"
                      >
                        {row.name || row.email}
                      </CommerceLink>
                      <span className="block text-xs text-muted-foreground">
                        {row.email}
                        {row.has_account ? "" : ", guest"}
                      </span>
                    </td>
                    <td className="p-3 tabular-nums">{row.order_count}</td>
                    <td className="p-3 text-right tabular-nums">
                      <Money value={row.spent} currency={row.currency} />
                    </td>
                    <td className="p-3">{new Date(row.last_order).toLocaleDateString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <nav aria-label="Pages" className="flex items-center justify-between gap-2 text-sm">
            <span>
              Page {page} of {pages}, {rows.data.count} customers
            </span>
            <span className="flex gap-2">
              <button
                type="button"
                className="rounded-md border border-border px-3 py-1 disabled:opacity-50"
                disabled={page <= 1}
                onClick={() => setPage(page - 1)}
              >
                Previous
              </button>
              <button
                type="button"
                className="rounded-md border border-border px-3 py-1 disabled:opacity-50"
                disabled={page >= pages}
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

function addressText(address: Address): string {
  return [
    address.name,
    address.line1,
    address.line2,
    `${address.postcode} ${address.city}`,
    address.country,
  ]
    .filter(Boolean)
    .join("\n");
}

export interface CustomerPageProps {
  email: string;
  siteName?: string;
  statusWords?: Partial<Record<string, string>>;
}

export function CustomerPage({ email, siteName, statusWords }: CustomerPageProps) {
  const client = useKarniClient();
  const { paths } = useCommerce();
  const words: Partial<Record<string, string>> = { ...ORDER_STATUS_WORDS, ...statusWords };
  const found = useQuery<CustomerPageData>({
    queryKey: ["karni-commerce", "customer", email],
    queryFn: ({ signal }) =>
      client.request<CustomerPageData>("/orders/customer/", { query: { email }, signal }),
  });
  usePageMeta({ title: found.data?.name || email, siteName });
  if (found.isPending) return <Skeleton className="h-96 w-full" />;
  if (found.isError) {
    return (
      <ErrorState
        error={found.error}
        context={{ action: "view", resource: "this customer" }}
        onRetry={() => void found.refetch()}
        actions={<CommerceLink to={paths.customers}>All customers</CommerceLink>}
      />
    );
  }
  const data = found.data;
  return (
    <article className="space-y-6">
      <nav aria-label="Breadcrumb" className="text-sm text-muted-foreground">
        <CommerceLink to={paths.customers} className="hover:underline">
          Customers
        </CommerceLink>{" "}
        / {data.name || data.email}
      </nav>
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold">{data.name || data.email}</h1>
        <p className="text-sm text-muted-foreground">
          {data.email}
          {data.account
            ? `, account since ${data.account.joined ? new Date(data.account.joined).toLocaleDateString() : "?"}`
            : ", ordered as a guest"}
        </p>
      </header>
      <dl className="grid gap-4 sm:grid-cols-3">
        <div className="rounded-lg border border-border p-4">
          <dt className="text-sm text-muted-foreground">Orders</dt>
          <dd className="text-2xl font-semibold tabular-nums">{data.order_count}</dd>
        </div>
        <div className="rounded-lg border border-border p-4">
          <dt className="text-sm text-muted-foreground">Total spent</dt>
          <dd className="text-2xl font-semibold tabular-nums">
            <Money value={data.spent} currency={data.currency} />
          </dd>
        </div>
        <div className="rounded-lg border border-border p-4">
          <dt className="text-sm text-muted-foreground">Customer since</dt>
          <dd className="text-2xl font-semibold">
            {new Date(data.first_order).toLocaleDateString()}
          </dd>
        </div>
      </dl>
      <section aria-label="Orders" className="space-y-2">
        <h2 className="font-semibold">Orders</h2>
        <ul className="divide-y divide-border rounded-lg border border-border">
          {data.orders.map((order) => (
            <li key={order.id}>
              <CommerceLink
                to={paths.order(order.number)}
                className="flex flex-wrap items-center justify-between gap-2 p-3 hover:bg-muted"
              >
                <span className="font-medium">Order {order.number}</span>
                <span className="text-sm text-muted-foreground">
                  {new Date(order.created_at).toLocaleDateString()}
                </span>
                <span className="text-sm">{words[order.status] ?? order.status}</span>
                <Money value={order.total} currency={data.currency} className="font-medium" />
              </CommerceLink>
            </li>
          ))}
        </ul>
      </section>
      <section aria-label="Addresses" className="space-y-2">
        <h2 className="font-semibold">Addresses</h2>
        {data.addresses.length === 0 ? (
          <p className="text-sm text-muted-foreground">No address given.</p>
        ) : (
          <ul className="grid gap-4 sm:grid-cols-2">
            {data.addresses.map((address, index) => (
              <li
                key={index}
                className="whitespace-pre-line rounded-lg border border-border p-4 text-sm"
              >
                {addressText(address)}
              </li>
            ))}
          </ul>
        )}
      </section>
    </article>
  );
}
