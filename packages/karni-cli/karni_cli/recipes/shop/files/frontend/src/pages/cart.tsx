// /cart: the cart (@karni/commerce-ui).
import { CartPage as Cart } from "@karni/commerce-ui";
import { SHOP_NAME } from "../shop/StoreLayout";

export default function CartPage() {
  return <Cart siteName={SHOP_NAME} />;
}
