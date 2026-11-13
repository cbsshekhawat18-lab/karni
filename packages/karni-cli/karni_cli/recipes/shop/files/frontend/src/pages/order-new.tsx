// /orders/new: staff place an order by hand for a customer who called (@karni/commerce-ui).
import { NewOrderPage } from "@karni/commerce-ui";
import { SHOP_NAME } from "../shop/StoreLayout";

export default function OrderNewPage() {
  return <NewOrderPage kind="product" siteName={SHOP_NAME} />;
}
