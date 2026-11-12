/** The signed-in person's orders, newest first, each a link to its page. */
import { EmptyState, ErrorState, Skeleton, usePageMeta, useResourceList } from "@karni/ui";
import { Money } from "./Money";
import { CommerceLink, useCommerce } from "./routes";
import { ORDER_STATUS_WORDS } from "./status";
import type { OrderRow } from "./types";

export interface MyOrdersProps {
  /** How many to show (the newest). */
  pageSize?: number;
  /** The heading level of the empty state's title. */
  headingLevel?: 2 | 3;
  statusWords?: Partial<Record<string, string>>;
}

export function MyOrders({ pageSize = 50, headingLevel = 3, statusWords }: MyOrdersProps) {
  const { paths } = useCommerce();
  const words: Partial<Record<string, string>> = { ...ORDER_STATUS_WORDS, ...statusWords };
  const orders = useResourceList<OrderRow>("orders", { pageSize, ordering: "-created_at" });
  if (orders.isPending) return <Skeleton className="h-40 w-full" />;
  if (orders.isError)
    return <ErrorState error={orders.error} onRetry={() => void orders.refetch()} />;
  const rows = orders.data.results;
  if (rows.length === 0) {
    return (
      <EmptyState
        title="No orders yet"
        headingLevel={headingLevel}
        action={<CommerceLink to={paths.browse}>Start shopping</CommerceLink>}
      />
    );
  }
  return (
    <ul aria-label="Your orders" className="divide-y divide-border rounded-lg border border-border">
      {rows.map((row) => (
        <li key={row.id}>
          <CommerceLink
            to={paths.order(row.number)}
            className="flex flex-wrap items-center justify-between gap-2 p-3 hover:bg-muted"
          >
            <span className="font-medium">Order {row.number}</span>
            <span className="text-sm text-muted-foreground">
              {new Date(row.created_at).toLocaleDateString()}
            </span>
            <span className="text-sm">{words[row.status] ?? row.status}</span>
            <Money value={row.total} currency={row.currency} className="font-medium" />
          </CommerceLink>
        </li>
      ))}
    </ul>
  );
}

export interface OrdersPageProps extends MyOrdersProps {
  title?: string;
  siteName?: string;
}

/** The /orders page: a heading and the person's orders. */
export function OrdersPage({ title = "Your orders", siteName, ...rest }: OrdersPageProps) {
  usePageMeta({ title, siteName });
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">{title}</h1>
      <MyOrders {...rest} />
    </div>
  );
}
