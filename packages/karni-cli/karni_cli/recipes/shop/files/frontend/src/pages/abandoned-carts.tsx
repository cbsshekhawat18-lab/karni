// /abandoned-carts: carts with items nobody touched for a while, with who left them when
// known (@karni/commerce-ui).
import { AbandonedCartsPage } from "@karni/commerce-ui";
import { useShopName } from "../shop/StoreLayout";

export default function AbandonedCarts() {
  return <AbandonedCartsPage siteName={useShopName()} />;
}
