// /checkout: contact, addresses and the payment (@karni/commerce-ui).
import { CheckoutPage as Checkout } from "@karni/commerce-ui";
import { useShopName } from "../shop/StoreLayout";

export default function CheckoutPage() {
  const shopName = useShopName();
  return <Checkout siteName={shopName} />;
}
