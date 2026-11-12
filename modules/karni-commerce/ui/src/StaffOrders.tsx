/**
 * Experimental. The staff's orders list: every order their grants give, newest
 * first, with search (number, email, name), filters by money state, date and
 * the buyer's email, sorting, paging and a CSV export, each row opening the
 * order's page. "New order" places one by hand for a buyer who called.
 *
 * It is @karni/ui's ResourceTable on `orders`, so the filters are the ones
 * the API declares and a project's extra filters show up too.
 */
import { Button, Page, ResourceTable, useAuth, type ResourceColumn } from "@karni/ui";
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

export function StaffOrders({ title = "Orders", canCreate = true }: StaffOrdersProps) {
  const { paths, navigate } = useCommerce();
  const { status } = useAuth();
  return (
    <Page
      title={title}
      actions={
        canCreate && status === "authenticated" ? (
          <Button onClick={() => navigate(paths.newOrder)}>New order</Button>
        ) : undefined
      }
    >
      <ResourceTable
        resource="orders"
        columns={COLUMNS}
        initialSorting={[{ id: "created_at", desc: true }]}
        onRowClick={(row) => navigate(paths.order(String(row["number"])))}
        caption="Orders"
      />
    </Page>
  );
}
