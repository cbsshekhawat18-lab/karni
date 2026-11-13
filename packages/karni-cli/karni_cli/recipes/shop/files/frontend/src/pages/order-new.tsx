// /orders/new: staff place an order by hand for a customer who called (@karni/commerce-ui).
import { NewOrderPage } from "@karni/commerce-ui";
import { useShopName } from "../shop/StoreLayout";

export default function OrderNewPage() {
  const shopName = useShopName();
  return <NewOrderPage kind="product" siteName={shopName} />;
}
