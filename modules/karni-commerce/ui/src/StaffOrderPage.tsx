/**
 * Experimental. One order as staff run it: where the money stands, the buyer,
 * the lines, the payments and refunds, the panels the selling apps add (the
 * shop's parcel), the notes and the history, with the moves the order allows
 * now: cancel, and refund all or part of it (by lines with the items back on
 * the shelf, or by an amount).
 *
 * The buttons follow the server: the order's declared row actions
 * (`x-karni-actions`) when the schema has them, else what the staff view
 * says (`can_cancel`, `can_refund`). The server checks every move again.
 */
import {
  Button,
  ChangeHistory,
  ErrorState,
  Input,
  Label,
  PendingButton,
  Skeleton,
  Textarea,
  rowActionOpen,
  useKarniClient,
  usePageMeta,
  useSchema,
  useToast,
} from "@karni/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";
import { problemOf } from "./cart";
import { Money } from "./Money";
import { LineDetails, OrderTotals } from "./Totals";
import { orderPanels } from "./panels";
import { CommerceLink, useCommerce } from "./routes";
import { ORDER_STATUS_WORDS } from "./status";
import type { Address, StaffOrder } from "./types";

export interface StaffOrderPageProps {
  number: string | number;
  siteName?: string;
  statusWords?: Partial<Record<string, string>>;
}

/** The query key of a staff order (invalidate it after a change made elsewhere). */
export const staffOrderKey = (number: string | number) =>
  ["karni-commerce", "staff-order", String(number)] as const;

function addressText(address: Address | Record<string, never>): string {
  if (!("line1" in address)) return "";
  return [
    address.name,
    address.company,
    address.line1,
    address.line2,
    `${address.postcode} ${address.city}`.trim(),
    address.region,
    address.country,
    address.phone,
  ]
    .filter(Boolean)
    .join("\n");
}

function Section({
  title,
  children,
  actions,
}: {
  title: string;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <section aria-label={title} className="space-y-3 rounded-lg border border-border p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">{title}</h2>
        {actions}
      </div>
      {children}
    </section>
  );
}

function RefundForm({ order, onDone }: { order: StaffOrder; onDone: () => void }) {
  const client = useKarniClient();
  const { toast } = useToast();
  const [byLines, setByLines] = useState(true);
  const [quantities, setQuantities] = useState<Record<string, number>>({});
  const [amount, setAmount] = useState("");
  const [restock, setRestock] = useState(true);
  const [reason, setReason] = useState("");
  const refund = useMutation({
    mutationFn: () =>
      client.request(`/orders/${order.id}/refund/`, {
        method: "POST",
        body: byLines
          ? {
              lines: Object.fromEntries(
                Object.entries(quantities).filter(([, quantity]) => quantity > 0),
              ),
              restock,
              reason,
            }
          : { amount, reason },
      }),
    onSuccess: () => {
      toast({ title: "Refund asked of the payment provider" });
      onDone();
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    refund.mutate();
  };
  return (
    <form onSubmit={submit} className="space-y-3" aria-label="Refund">
      <fieldset className="flex flex-wrap gap-4 text-sm">
        <legend className="sr-only">Refund by</legend>
        <label className="flex items-center gap-2">
          <input type="radio" checked={byLines} onChange={() => setByLines(true)} />
          By items
        </label>
        <label className="flex items-center gap-2">
          <input type="radio" checked={!byLines} onChange={() => setByLines(false)} />
          By amount
        </label>
      </fieldset>
      {byLines ? (
        <>
          <ul className="space-y-2">
            {order.lines.map((line) => {
              const left = line.quantity - line.quantity_refunded;
              return (
                <li key={line.id} className="flex flex-wrap items-center gap-3 text-sm">
                  <Label htmlFor={`refund-${line.id}`} className="min-w-0 flex-1">
                    {line.name}{" "}
                    <span className="text-muted-foreground">
                      ({left} of {line.quantity} left to refund)
                    </span>
                  </Label>
                  <Input
                    id={`refund-${line.id}`}
                    type="number"
                    min={0}
                    max={left}
                    disabled={left === 0}
                    className="w-20"
                    value={quantities[line.id] ?? 0}
                    onChange={(event) =>
                      setQuantities({
                        ...quantities,
                        [line.id]: Math.max(0, Math.min(left, Number(event.target.value) || 0)),
                      })
                    }
                  />
                </li>
              );
            })}
          </ul>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={restock}
              onChange={(event) => setRestock(event.target.checked)}
            />
            Put the items back in stock
          </label>
        </>
      ) : (
        <div className="space-y-1">
          <Label htmlFor="refund-amount">
            Amount (at most <Money value={order.refundable} currency={order.currency} />)
          </Label>
          <Input
            id="refund-amount"
            inputMode="decimal"
            className="w-40"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
          />
        </div>
      )}
      <div className="space-y-1">
        <Label htmlFor="refund-reason">Reason (the buyer sees it)</Label>
        <Input
          id="refund-reason"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      </div>
      {refund.isError ? (
        <p role="alert" className="text-sm text-destructive">
          {problemOf(refund.error)}
        </p>
      ) : null}
      <PendingButton type="submit" pending={refund.isPending}>
        Refund
      </PendingButton>
    </form>
  );
}

function Notes({ order, onDone }: { order: StaffOrder; onDone: () => void }) {
  const client = useKarniClient();
  const [body, setBody] = useState("");
  const [toCustomer, setToCustomer] = useState(false);
  const write = useMutation({
    mutationFn: () =>
      client.request(`/orders/${order.id}/notes/`, {
        method: "POST",
        body: { body, kind: toCustomer ? "customer" : "internal" },
      }),
    onSuccess: () => {
      setBody("");
      setToCustomer(false);
      onDone();
    },
  });
  return (
    <Section title="Notes">
      {order.notes.length === 0 ? (
        <p className="text-sm text-muted-foreground">No notes yet.</p>
      ) : (
        <ul className="space-y-2">
          {order.notes.map((note) => (
            <li key={note.id} className="rounded-md bg-muted p-3 text-sm">
              <p className="whitespace-pre-line">{note.body}</p>
              <p className="text-xs text-muted-foreground">
                {note.kind === "customer" ? "To the customer" : "Internal"}
                {note.author_name ? `, ${note.author_name}` : ""},{" "}
                {new Date(note.created_at).toLocaleString()}
              </p>
            </li>
          ))}
        </ul>
      )}
      <form
        className="space-y-2"
        onSubmit={(event) => {
          event.preventDefault();
          write.mutate();
        }}
      >
        <Label htmlFor="order-note">Add a note</Label>
        <Textarea
          id="order-note"
          value={body}
          rows={3}
          onChange={(event) => setBody(event.target.value)}
        />
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={toCustomer}
            onChange={(event) => setToCustomer(event.target.checked)}
          />
          Send it to the customer (by email, and on their order page)
        </label>
        {write.isError ? (
          <p role="alert" className="text-sm text-destructive">
            {problemOf(write.error)}
          </p>
        ) : null}
        <PendingButton type="submit" variant="outline" pending={write.isPending}>
          Add note
        </PendingButton>
      </form>
    </Section>
  );
}

export function StaffOrderPage({ number, siteName, statusWords }: StaffOrderPageProps) {
  const client = useKarniClient();
  const queryClient = useQueryClient();
  const { paths } = useCommerce();
  const schema = useSchema("orders");
  const words: Partial<Record<string, string>> = { ...ORDER_STATUS_WORDS, ...statusWords };
  const [refunding, setRefunding] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const order = useQuery<StaffOrder>({
    queryKey: staffOrderKey(number),
    queryFn: async ({ signal }) => {
      const found = await client.request<{ id: string }>("/orders/lookup/", {
        query: { number },
        signal,
      });
      return client.request<StaffOrder>(`/orders/${found.id}/staff/`, { signal });
    },
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: staffOrderKey(number) });
  const cancel = useMutation({
    mutationFn: (id: string) =>
      client.request(`/orders/${id}/cancel/`, { method: "POST", body: {} }),
    onSuccess: () => {
      setCancelling(false);
      refresh();
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
        actions={<CommerceLink to={paths.orders}>All orders</CommerceLink>}
      />
    );
  }
  const data = order.data;
  const row = data as unknown as Record<string, unknown>;
  const canCancel = rowActionOpen(schema.data, "cancel", row) ?? data.can_cancel;
  const canRefund = rowActionOpen(schema.data, "refund", row) ?? data.can_refund;
  const panels = orderPanels(data);
  return (
    <article className="space-y-6">
      <header className="space-y-2">
        <nav aria-label="Breadcrumb" className="text-sm text-muted-foreground">
          <CommerceLink to={paths.orders} className="hover:underline">
            Orders
          </CommerceLink>{" "}
          / {data.number}
        </nav>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="text-2xl font-semibold">Order {data.number}</h1>
          <span className="rounded-full bg-muted px-3 py-1 text-sm font-medium">
            {words[data.status] ?? data.status}
          </span>
        </div>
        <p className="text-sm text-muted-foreground">
          Placed {new Date(data.created_at).toLocaleString()}
          {data.paid_at ? `, paid ${new Date(data.paid_at).toLocaleString()}` : ""}
          {data.cancelled_at ? `, cancelled ${new Date(data.cancelled_at).toLocaleString()}` : ""}
        </p>
        <div className="flex flex-wrap gap-2">
          {canRefund ? (
            <Button variant="outline" onClick={() => setRefunding(!refunding)}>
              {refunding ? "Close the refund" : "Refund"}
            </Button>
          ) : null}
          {canCancel ? (
            <Button variant="outline" onClick={() => setCancelling(true)}>
              Cancel order
            </Button>
          ) : null}
        </div>
        {cancelling ? (
          <div
            role="alertdialog"
            aria-label="Cancel the order"
            className="space-y-2 rounded-lg border border-border p-4"
          >
            <p className="text-sm">
              Cancel order {data.number}?{" "}
              {Number(data.amount_paid) > 0
                ? "What was paid goes back to the buyer, and the items go back on the shelf."
                : "The items it holds are free again."}
            </p>
            {cancel.isError ? (
              <p role="alert" className="text-sm text-destructive">
                {problemOf(cancel.error)}
              </p>
            ) : null}
            <div className="flex gap-2">
              <PendingButton
                variant="destructive"
                pending={cancel.isPending}
                onClick={() => cancel.mutate(data.id)}
              >
                Cancel the order
              </PendingButton>
              <Button variant="ghost" onClick={() => setCancelling(false)}>
                Keep it
              </Button>
            </div>
          </div>
        ) : null}
      </header>
      {refunding ? (
        <Section title="Refund">
          <RefundForm
            order={data}
            onDone={() => {
              setRefunding(false);
              refresh();
            }}
          />
        </Section>
      ) : null}
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Section title="Items">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-muted-foreground">
                    <th scope="col" className="py-2 pr-3 font-medium">
                      Item
                    </th>
                    <th scope="col" className="py-2 pr-3 font-medium">
                      Quantity
                    </th>
                    <th scope="col" className="py-2 pr-3 text-right font-medium">
                      Price
                    </th>
                    <th scope="col" className="py-2 text-right font-medium">
                      Total
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data.lines.map((line) => (
                    <tr key={line.id} className="border-b border-border last:border-0">
                      <td className="py-2 pr-3">
                        {line.name}
                        <LineDetails details={line.details} className="text-xs" />
                        {line.sku ? (
                          <span className="block text-xs text-muted-foreground">{line.sku}</span>
                        ) : null}
                      </td>
                      <td className="py-2 pr-3">
                        {line.quantity}
                        {line.quantity_refunded > 0 ? (
                          <span className="block text-xs text-muted-foreground">
                            {line.quantity_refunded} refunded
                          </span>
                        ) : null}
                      </td>
                      <td className="py-2 pr-3 text-right tabular-nums">
                        <Money value={line.unit_price} currency={data.currency} />
                      </td>
                      <td className="py-2 text-right tabular-nums">
                        <Money value={line.line_total} currency={data.currency} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <OrderTotals order={data} className="ml-auto max-w-xs text-sm" />
            <dl className="ml-auto max-w-xs space-y-1 text-sm">
              {[
                ["Paid", data.amount_paid],
                ["Refunded", data.amount_refunded],
                ["Can still be refunded", data.refundable],
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between gap-4">
                  <dt>{label}</dt>
                  <dd className="tabular-nums">
                    <Money value={value ?? "0"} currency={data.currency} />
                  </dd>
                </div>
              ))}
            </dl>
          </Section>
          {panels.map((panel) => (
            <Section key={panel.key} title={panel.title}>
              <panel.component order={data} refresh={refresh} />
            </Section>
          ))}
          <Section title="Payments">
            {data.payments.length === 0 ? (
              <p className="text-sm text-muted-foreground">No payment yet.</p>
            ) : (
              <ul className="space-y-1 text-sm">
                {data.payments.map((payment) => (
                  <li key={payment.id} className="flex flex-wrap justify-between gap-2">
                    <span>
                      {new Date(payment.created_at).toLocaleString()}, {payment.provider},{" "}
                      {payment.status.replace(/_/g, " ")}
                    </span>
                    <Money value={payment.amount} currency={data.currency} />
                  </li>
                ))}
              </ul>
            )}
            {data.refunds.length > 0 ? (
              <>
                <h3 className="pt-2 text-sm font-semibold">Refunds</h3>
                <ul className="space-y-1 text-sm">
                  {data.refunds.map((refund) => (
                    <li key={refund.id} className="flex flex-wrap justify-between gap-2">
                      <span>
                        {new Date(refund.created_at).toLocaleString()},{" "}
                        {refund.status.replace(/_/g, " ")}
                        {refund.restock ? ", back in stock" : ""}
                        {refund.reason ? `: ${refund.reason}` : ""}
                      </span>
                      <Money value={refund.amount} currency={data.currency} />
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
          </Section>
          <Notes order={data} onDone={refresh} />
          <div className="rounded-lg border border-border p-4">
            <ChangeHistory resource="orders" id={data.id} record={{ currency: data.currency }} />
          </div>
        </div>
        <div className="space-y-6">
          <Section title="Customer">
            <p className="text-sm">
              <CommerceLink to={paths.customer(data.email)} className="font-medium hover:underline">
                {data.buyer.name || data.email}
              </CommerceLink>
              <span className="block text-muted-foreground">{data.email}</span>
              <span className="block text-muted-foreground">
                {data.buyer.user ? "Has an account. " : "Ordered as a guest. "}
                {data.buyer.orders} {data.buyer.orders === 1 ? "order" : "orders"},{" "}
                <Money value={data.buyer.spent} currency={data.currency} /> spent
              </span>
            </p>
          </Section>
          <Section title="Addresses">
            <h3 className="text-sm font-semibold">Billing</h3>
            <p className="whitespace-pre-line text-sm">{addressText(data.billing)}</p>
            {data.needs_shipping ? (
              <>
                <h3 className="text-sm font-semibold">Shipping</h3>
                <p className="whitespace-pre-line text-sm">{addressText(data.shipping)}</p>
              </>
            ) : null}
          </Section>
          {data.note ? (
            <Section title="The customer's note">
              <p className="whitespace-pre-line text-sm">{data.note}</p>
            </Section>
          ) : null}
        </div>
      </div>
    </article>
  );
}
