// /checkout: contact, addresses and the payment (@karni/commerce-ui).
import { CheckoutPage as Checkout } from "@karni/commerce-ui";
import { SHOP_NAME } from "../shop/StoreLayout";

export default function CheckoutPage() {
  return <Checkout siteName={SHOP_NAME} />;
}
