// /cart: the cart (@karni/commerce-ui).
import { CartPage as Cart } from "@karni/commerce-ui";
import { useShopName } from "../shop/StoreLayout";

export default function CartPage() {
  const shopName = useShopName();
  return <Cart siteName={shopName} />;
}
