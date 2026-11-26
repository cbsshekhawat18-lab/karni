/**
 * The staff's orders list: every order their grants give, newest
 * first, with search (number, email, name), filters by money state and by the
 * day it was placed, sorting, paging and a CSV export, each row opening the
 * order's page. "New order" places one by hand for a buyer who called.
 *
 * It is @karni/ui's ResourceTable on `orders`, so the filters are the ones
 * the API declares and a project's extra filters show up too.
 */
import { Button, Input, Label, Page, ResourceTable, useAuth, type ResourceColumn } from "@karni/ui";
import { useMemo, useState } from "react";
import { useCommerce } from "./routes";

export interface StaffOrdersProps {
  title?: string;
  /** Show "New order" (an order placed by hand). The server checks `karni_commerce.order:add`. */
  canCreate?: boolean;
}

const COLUMNS: ReadonlyArray<ResourceColumn> = [
  { field: "number", header: "Order" },
  { field: "created_at", header: "Placed" },
  { field: "buyer_name", header: "Customer" },
  { field: "email" },
  { field: "status" },
  { field: "total" },
  { field: "paid_at", hidden: true },
  { field: "reference", hidden: true },
  { field: "user", hidden: true },
  { field: "subtotal", hidden: true },
  { field: "discount_total", hidden: true },
  { field: "shipping_total", hidden: true },
  { field: "tax_total", hidden: true },
  { field: "tax_lines", hidden: true },
  { field: "prices_include_tax", hidden: true },
  { field: "coupon_code", hidden: true },
  { field: "shipping_method", hidden: true },
  { field: "amount_paid", hidden: true },
  { field: "amount_refunded", hidden: true },
  { field: "currency", hidden: true },
  { field: "billing", hidden: true },
  { field: "shipping", hidden: true },
  { field: "needs_shipping", hidden: true },
  { field: "note", hidden: true },
  { field: "hold_until", hidden: true },
  { field: "cancelled_at", hidden: true },
];

/** The start of a day (`from`) or of the next one (`to`) as the API's datetime filters take it. */
function dayParams(from: string, to: string): Record<string, string> {
  const found: Record<string, string> = {};
  if (from) found["created_at__gte"] = new Date(`${from}T00:00:00`).toISOString();
  if (to) {
    const end = new Date(`${to}T00:00:00`);
    end.setDate(end.getDate() + 1);
    found["created_at__lte"] = end.toISOString();
  }
  return found;
}

export function StaffOrders({ title = "Orders", canCreate = true }: StaffOrdersProps) {
  const { paths, navigate } = useCommerce();
  const { status } = useAuth();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const params = useMemo(() => dayParams(from, to), [from, to]);
  return (
    <Page
      title={title}
      actions={
        canCreate && status === "authenticated" ? (
          <Button onClick={() => navigate(paths.newOrder)}>New order</Button>
        ) : undefined
      }
    >
      <div className="flex flex-wrap items-end gap-3" role="group" aria-label="Placed between">
        <div className="space-y-1">
          <Label htmlFor="orders-from">Placed from</Label>
          <Input
            id="orders-from"
            type="date"
            className="h-9"
            value={from}
            onChange={(event) => setFrom(event.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="orders-to">to</Label>
          <Input
            id="orders-to"
            type="date"
            className="h-9"
            value={to}
            onChange={(event) => setTo(event.target.value)}
          />
        </div>
      </div>
      <ResourceTable
        resource="orders"
        columns={COLUMNS}
        params={params}
        filters={["status"]}
        importable={false}
        initialSorting={[{ id: "created_at", desc: true }]}
        onRowClick={(row) => navigate(paths.order(String(row["number"])))}
        caption="Orders"
      />
    </Page>
  );
}
