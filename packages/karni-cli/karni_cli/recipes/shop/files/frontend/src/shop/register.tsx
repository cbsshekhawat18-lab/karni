// What the shop adds to the family pages, once at startup: the orders section of /account.
import { MyOrders } from "@karni/commerce-ui";
import { registerAccountSection } from "@karni/ui";

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
}
