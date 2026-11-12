// /orders: the signed-in person's orders (@karni/commerce-ui).
import { OrdersPage as Orders } from "@karni/commerce-ui";
import { SHOP_NAME } from "../shop/StoreLayout";

export default function OrdersPage() {
  return <Orders siteName={SHOP_NAME} />;
}
