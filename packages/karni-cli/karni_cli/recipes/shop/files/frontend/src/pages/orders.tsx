// /orders: for staff every order (search, filters by state, date and customer), for a
// customer their own (@karni/commerce-ui).
import { OrdersPage as Orders, StaffOrders } from "@karni/commerce-ui";
import { SHOP_NAME } from "../shop/StoreLayout";
import { usePerson } from "../shop/staff";

export default function OrdersPage() {
  const person = usePerson();
  if (person === "loading") return null;
  return person === "staff" ? <StaffOrders /> : <Orders siteName={SHOP_NAME} />;
}
