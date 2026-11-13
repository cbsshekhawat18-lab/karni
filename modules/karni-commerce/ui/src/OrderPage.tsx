/**
 * One order as its buyer reads it: where the money stands, what the seller
 * reports about the goods, the lines and totals and the addresses. A guest
 * reads it with the key from checkout (the link in the confirmation email).
 * Right after paying (`justPaid`) it checks every 2 seconds until the
 * payment is confirmed.
 */
import {
  Button,
  ErrorState,
  PendingButton,
  Skeleton,
  useKarniClient,
  usePageMeta,
} from "@karni/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { problemOf } from "./cart";
import { ItemImage } from "./ItemImage";
import { Money } from "./Money";
import { LineDetails, OrderTotals } from "./Totals";
import { CommerceLink, useCommerce } from "./routes";
import { ORDER_STATUS_WORDS } from "./status";
import type { Address, Order } from "./types";

export interface OrderPageProps {
  number: string | number;
  /** The guest's key (the `key` search value). */
  orderKey?: string;
  /** The payment page sent the person back (`paid=1`): wait for the confirmation. */
  justPaid?: boolean;
  siteName?: string;
  statusWords?: Partial<Record<string, string>>;
}

function countryName(code: string): string {
  try {
    return new Intl.DisplayNames(undefined, { type: "region" }).of(code) ?? code;
  } catch {
    return code;
  }
}

function lines(address: Address): string {
  return [
    address.name,
    address.company,
    address.line1,
    address.line2,
    `${address.postcode} ${address.city}`.trim(),
    address.region,
    address.country ? countryName(address.country) : "",
  ]
    .filter(Boolean)
    .join("\n");
}

function AddressBlock({ title, address }: { title: string; address: Address }) {
  return (
    <section className="space-y-1">
      <h2 className="font-semibold">{title}</h2>
      <p className="whitespace-pre-line text-sm">{lines(address)}</p>
    </section>
  );
}

function Banner({ order, justPaid }: { order: Order; justPaid: boolean }) {
  if (order.status === "pending" && justPaid) {
    return <p role="status">Your payment is being confirmed. This page updates by itself.</p>;
  }
  if (order.status === "paid") {
    return (
      <p role="status" className="rounded-md bg-muted p-4">
        Thank you. Your order is confirmed, and the confirmation is on its way to {order.email}.
      </p>
    );
  }
  if (order.status === "failed") {
    return (
      <p role="alert" className="rounded-md bg-muted p-4">
        The payment did not go through, and nothing was charged. You can try again.
      </p>
    );
  }
  return null;
}

export function OrderPage({
  number,
  orderKey = "",
  justPaid = false,
  siteName,
  statusWords,
}: OrderPageProps) {
  const client = useKarniClient();
  const { paths } = useCommerce();
  const words: Partial<Record<string, string>> = { ...ORDER_STATUS_WORDS, ...statusWords };
  const order = useQuery<Order>({
    queryKey: ["karni-commerce", "order", String(number), orderKey],
    queryFn: ({ signal }) =>
      client.request<Order>("/orders/lookup/", { query: { number, key: orderKey }, signal }),
    refetchInterval: (query) => (justPaid && query.state.data?.status === "pending" ? 2000 : false),
  });
  const pay = useMutation({
    mutationFn: () =>
      client.request<{ url: string | null }>("/orders/pay/", {
        method: "POST",
        body: { number: Number(number), key: orderKey },
      }),
    onSuccess: (result) => {
      if (result.url) window.location.assign(result.url);
      else void order.refetch();
    },
  });
  usePageMeta({ title: `Order ${number}`, siteName });
  if (order.isPending) return <Skeleton className="h-96 w-full" />;
  if (order.isError) {
    return (
      <ErrorState
        error={order.error}
        context={{ action: "view", resource: "this order" }}
        onRetry={() => void order.refetch()}
        actions={<CommerceLink to={paths.orders}>Your orders</CommerceLink>}
      />
    );
  }
  const data = order.data;
  const shipping = "line1" in data.shipping ? (data.shipping as Address) : null;
  return (
    <article className="space-y-6">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-2xl font-semibold">Order {data.number}</h1>
        <span className="rounded-full bg-muted px-3 py-1 text-sm font-medium">
          {words[data.status] ?? data.status}
        </span>
      </header>
      <Banner order={data} justPaid={justPaid} />
      {data.payable ? (
        <div className="space-y-2">
          {pay.isError ? (
            <p role="alert" className="text-destructive">
              {problemOf(pay.error)}
            </p>
          ) : null}
          <PendingButton pending={pay.isPending} onClick={() => pay.mutate()}>
            {data.status === "failed" ? "Try the payment again" : "Pay now"}
          </PendingButton>
        </div>
      ) : null}
      {data.fulfilment.length > 0 ? (
        <section aria-label="Delivery" className="space-y-2 rounded-lg border border-border p-4">
          {data.fulfilment.map((entry, index) => (
            <p key={`${entry.title}-${index}`} className="text-sm">
              <span className="font-medium">{entry.title}: </span>
              {entry.label}
              {entry.detail ? (
                <span className="text-muted-foreground">, {entry.detail}</span>
              ) : null}
              {entry.at ? (
                <span className="text-muted-foreground">
                  {" "}
                  ({new Date(entry.at).toLocaleDateString()})
                </span>
              ) : null}
            </p>
          ))}
        </section>
      ) : null}
      <ul className="divide-y divide-border rounded-lg border border-border">
        {data.lines.map((line) => (
          <li key={line.id} className="flex items-center gap-4 p-3">
            <div className="w-14 shrink-0">
              <ItemImage src={line.image} />
            </div>
            <span className="min-w-0 flex-1">
              {line.url ? (
                <CommerceLink to={line.url} className="hover:underline">
                  {line.name}
                </CommerceLink>
              ) : (
                line.name
              )}
              <LineDetails details={line.details} />
              <span className="block text-sm text-muted-foreground">
                {line.quantity} x <Money value={line.unit_price} currency={data.currency} />
                {line.quantity_refunded > 0 ? `, ${line.quantity_refunded} refunded` : ""}
              </span>
            </span>
            <Money value={line.line_total} currency={data.currency} className="font-medium" />
          </li>
        ))}
      </ul>
      <OrderTotals order={data} className="ml-auto max-w-xs" />
      <dl className="ml-auto max-w-xs space-y-1">
        {Number(data.amount_refunded) > 0 ? (
          <div className="flex justify-between text-sm">
            <dt>Refunded</dt>
            <dd>
              <Money value={data.amount_refunded} currency={data.currency} />
            </dd>
          </div>
        ) : null}
      </dl>
      <div className="grid gap-6 sm:grid-cols-2">
        <AddressBlock title="Billing" address={data.billing} />
        {shipping ? <AddressBlock title="Shipping" address={shipping} /> : null}
      </div>
      {data.note ? <p className="text-sm">Your note: {data.note}</p> : null}
      {data.notes.length > 0 ? (
        <section aria-label="Notes from the shop" className="space-y-2">
          <h2 className="font-semibold">Notes from us</h2>
          {data.notes.map((note) => (
            <p key={note.id} className="whitespace-pre-line rounded-md bg-muted p-3 text-sm">
              {note.body}
              <span className="block text-xs text-muted-foreground">
                {new Date(note.created_at).toLocaleString()}
              </span>
            </p>
          ))}
        </section>
      ) : null}
      <p className="text-sm text-muted-foreground">
        Placed {new Date(data.created_at).toLocaleString()}
        {data.paid_at ? `, paid ${new Date(data.paid_at).toLocaleString()}` : ""}.
      </p>
      <Button variant="outline" onClick={() => window.print()}>
        Print
      </Button>
    </article>
  );
}
