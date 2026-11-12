// One order as its customer sees it: where it stands, its lines and totals, the addresses.
// A guest reads it with the key from checkout (the link in the confirmation email).
import {
  Button,
  EmptyState,
  ErrorState,
  PendingButton,
  Skeleton,
  useKarniClient,
  usePageMeta,
} from "@karni/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { problemOf } from "./cart";
import { ProductImageBox } from "./ProductCard";
import { Money } from "./Price";
import { SHOP_NAME } from "./StoreLayout";
import type { Address, Order } from "./types";

export const STATUS_WORDS: Record<string, string> = {
  pending: "Waiting for payment",
  paid: "Paid",
  processing: "Being prepared",
  shipped: "Shipped",
  delivered: "Delivered",
  failed: "Payment failed",
  cancelled: "Cancelled",
  refunded: "Refunded",
};

function AddressBlock({ title, address }: { title: string; address: Address }) {
  return (
    <section className="space-y-1">
      <h3 className="font-semibold">{title}</h3>
      <p className="whitespace-pre-line text-sm">
        {[
          address.name,
          address.company,
          address.line1,
          address.line2,
          `${address.postcode} ${address.city}`,
          address.region,
          address.country,
        ]
          .filter(Boolean)
          .join("\n")}
      </p>
    </section>
  );
}

function Banner({ order, justPaid }: { order: Order; justPaid: boolean }) {
  if (order.status === "pending" && justPaid) {
    return (
      <p role="status">
        Your payment is being confirmed. This page updates by itself.
      </p>
    );
  }
  if (order.status === "paid" || order.status === "processing") {
    return (
      <p role="status" className="rounded-md bg-muted p-4">
        Thank you. Your order is confirmed, and the confirmation is on its way
        to {order.email}.
      </p>
    );
  }
  if (order.status === "failed") {
    return (
      <p role="alert">
        The payment did not go through, and nothing was charged. The items went
        back on the shelf.
      </p>
    );
  }
  return null;
}

export function OrderView({
  number,
  orderKey,
  justPaid,
}: {
  number: string;
  orderKey: string;
  justPaid: boolean;
}) {
  const client = useKarniClient();
  const order = useQuery<Order>({
    queryKey: ["shop", "order", number, orderKey],
    queryFn: ({ signal }) =>
      client.request<Order>("/orders/lookup/", {
        query: { number, key: orderKey },
        signal,
      }),
    refetchInterval: (query) =>
      justPaid && query.state.data?.status === "pending" ? 2000 : false,
  });
  const pay = useMutation({
    mutationFn: () =>
      client.request<{ url: string }>("/orders/pay/", {
        method: "POST",
        body: { number: Number(number), key: orderKey },
      }),
    onSuccess: (result) => window.location.assign(result.url),
  });
  usePageMeta({ title: `Order ${number}`, siteName: SHOP_NAME });
  if (order.isPending) return <Skeleton className="h-96 w-full" />;
  if (order.isError) {
    return (
      <ErrorState
        error={order.error}
        context={{ action: "view", resource: "this order" }}
        onRetry={() => void order.refetch()}
        actions={<Link to="/account">Your orders</Link>}
      />
    );
  }
  const data = order.data;
  return (
    <article className="space-y-6">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-2xl font-semibold">Order {data.number}</h1>
        <span className="rounded-full bg-muted px-3 py-1 text-sm font-medium">
          {STATUS_WORDS[data.status] ?? data.status}
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
            Pay now
          </PendingButton>
        </div>
      ) : null}
      <ul className="divide-y divide-border rounded-lg border border-border">
        {data.lines.map((line) => (
          <li key={line.id} className="flex items-center gap-4 p-3">
            <div className="w-14">
              <ProductImageBox src={line.image} alt="" />
            </div>
            <span className="min-w-0 flex-1">
              {line.slug ? (
                <Link
                  to="/shop/$slug"
                  params={{ slug: line.slug }}
                  className="hover:underline"
                >
                  {line.name}
                </Link>
              ) : (
                line.name
              )}
              <span className="block text-sm text-muted-foreground">
                {line.quantity} x <Money value={line.unit_price} />
              </span>
            </span>
            <Money value={line.line_total} className="font-medium" />
          </li>
        ))}
      </ul>
      <dl className="ml-auto max-w-xs space-y-1">
        <div className="flex justify-between">
          <dt>Subtotal</dt>
          <dd>
            <Money value={data.subtotal} />
          </dd>
        </div>
        <div className="flex justify-between text-lg font-semibold">
          <dt>Total</dt>
          <dd>
            <Money value={data.total} />
          </dd>
        </div>
      </dl>
      <div className="grid gap-6 sm:grid-cols-2">
        <AddressBlock title="Billing" address={data.billing} />
        <AddressBlock title="Shipping" address={data.shipping} />
      </div>
      {data.note ? <p className="text-sm">Your note: {data.note}</p> : null}
      <p className="text-sm text-muted-foreground">
        Placed {new Date(data.created_at).toLocaleString()}
        {data.paid_at
          ? `, paid ${new Date(data.paid_at).toLocaleString()}`
          : ""}
        .
      </p>
      <Button variant="outline" onClick={() => window.print()}>
        Print
      </Button>
    </article>
  );
}

export function NoOrder() {
  return (
    <EmptyState
      title="No such order"
      action={<Link to="/shop">Back to the shop</Link>}
    />
  );
}
