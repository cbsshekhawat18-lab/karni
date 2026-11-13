// /customers/$email: one customer's orders, what they spent and their addresses.
import { CustomerPage } from "@karni/commerce-ui";
import { useParams } from "@tanstack/react-router";
import { useShopName } from "../shop/StoreLayout";

export default function Customer() {
  const shopName = useShopName();
  const { email } = useParams({ from: "/shop/customers/$email" });
  return <CustomerPage email={decodeURIComponent(email)} siteName={shopName} />;
}
