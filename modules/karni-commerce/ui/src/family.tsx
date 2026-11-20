/**
 * Experimental. Commerce's part of the family pages.
 *
 * - `FamilyOrdersPage` is `/orders`: every order for staff (`StaffOrders`),
 *   a customer's own (`OrdersPage`).
 * - `FamilyOrderPage` is `/orders/<number>`: the order to run for staff
 *   (`StaffOrderPage`), the order and its confirmation for its buyer or a
 *   guest with the key (`OrderPage`).
 * - `PersonOrders` is the Orders tab of the person page (`/people/<id>`):
 *   that person's orders, newest first, each opening its page.
 * - `register()` adds them once at startup: "Your orders" on `/account`,
 *   the Orders tab of the person page, and the link from any table, page or
 *   search hit that shows an order (its number) to that order. The build's
 *   `parts.ts` calls it when the project holds commerce.
 *
 * Staff is anyone with a role beyond the family's `customer`
 * (`useAudience`). The server decides what each may read.
 */
import {
  registerAccountSection,
  registerPersonTab,
  registerRecordLink,
  ResourceTable,
  useAudience,
  type PersonTabProps,
  type ResourceColumn,
} from "@karni/ui";
import { MyOrders, OrdersPage } from "./MyOrders";
import { OrderPage } from "./OrderPage";
import { useCommerce } from "./routes";
import { StaffOrderPage } from "./StaffOrderPage";
import { StaffOrders } from "./StaffOrders";

export interface FamilyOrdersPageProps {
  siteName?: string;
}

/** Experimental. `/orders`: every order for staff, a customer's own orders. */
export function FamilyOrdersPage({ siteName }: FamilyOrdersPageProps) {
  const audience = useAudience();
  if (audience === "loading") return null;
  return audience === "staff" ? <StaffOrders /> : <OrdersPage siteName={siteName} />;
}

export interface FamilyOrderPageProps {
  number: string | number;
  /** The guest's key (the `key` search value). */
  orderKey?: string;
  /** The payment page sent the buyer back (`paid=1`). */
  justPaid?: boolean;
  siteName?: string;
}

/** Experimental. `/orders/<number>`: the order to run for staff, the order for its buyer. */
export function FamilyOrderPage({
  number,
  orderKey = "",
  justPaid = false,
  siteName,
}: FamilyOrderPageProps) {
  const audience = useAudience();
  if (audience === "loading") return null;
  if (audience === "staff") return <StaffOrderPage number={number} siteName={siteName} />;
  return <OrderPage number={number} orderKey={orderKey} justPaid={justPaid} siteName={siteName} />;
}

const PERSON_COLUMNS: ReadonlyArray<ResourceColumn> = [
  "number",
  "created_at",
  "status",
  "total",
].map((field) => ({ field, ...(field === "number" ? { header: "Order" } : {}) }));

/** Experimental. The Orders tab of the person page: one person's orders. */
export function PersonOrders({ personId }: PersonTabProps) {
  const { paths, navigate } = useCommerce();
  return (
    <ResourceTable
      resource="orders"
      params={{ person: personId }}
      columns={PERSON_COLUMNS}
      filters={["status"]}
      importable={false}
      exportFormats={false}
      syncUrl={false}
      initialSorting={[{ id: "created_at", desc: true }]}
      caption="Orders"
      onRowClick={(row) => navigate(paths.order(String(row["number"])))}
    />
  );
}

function YourOrders() {
  return <MyOrders pageSize={5} />;
}

/** Experimental. Commerce's sections, tab and record links on the family pages. */
export function register(): void {
  registerAccountSection({ key: "orders", title: "Your orders", order: 10, component: YourOrders });
  registerPersonTab({ key: "orders", title: "Orders", order: 10, component: PersonOrders });
  // A row of the orders list has its number; a search hit has it as its title.
  registerRecordLink("orders", (row) => {
    const number = row["number"] ?? row["title"];
    return number !== undefined && number !== null && number !== ""
      ? `/orders/${encodeURIComponent(String(number))}`
      : null;
  });
}
