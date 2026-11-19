// /orders/new: staff place an order by hand for a customer who called (@karni/commerce-ui):
// any kind the project sells, the shop's products and what other parts sell beside them.
import { NewOrderPage } from "@karni/commerce-ui";
import { useShopName } from "../shop/StoreLayout";

export default function OrderNewPage() {
  const shopName = useShopName();
  return <NewOrderPage siteName={shopName} />;
}
