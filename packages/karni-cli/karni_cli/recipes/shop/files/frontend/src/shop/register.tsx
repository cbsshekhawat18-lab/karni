// What the shop adds to the family pages, once at startup: the orders section of
// /account, the parcel panel on the staff's order page, links from any table or page
// that shows an order (its number) to that order, and categories as a coupon limit.
import {
  MyOrders,
  registerCouponLimit,
  registerOrderPanel,
} from "@karni/commerce-ui";
import { registerAccountSection, registerRecordLink } from "@karni/ui";
import { ParcelPanel } from "./ParcelPanel";

function Orders() {
  return <MyOrders pageSize={5} />;
}

export function registerShop(): void {
  registerAccountSection({
    key: "orders",
    title: "Your orders",
    order: 10,
    component: Orders,
  });
  registerOrderPanel({
    key: "parcel",
    title: "Parcel",
    order: 10,
    component: ParcelPanel,
    kinds: ["product"],
    when: (order) => order.needs_shipping,
  });
  registerCouponLimit({
    key: "categories",
    label: "Categories",
    resource: "categories",
    labelField: "name",
  });
  registerRecordLink("orders", (row) =>
    row["number"] != null ? `/orders/${String(row["number"])}` : null,
  );
}
