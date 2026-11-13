// /customers/$email: one customer's orders, what they spent and their addresses.
import { CustomerPage } from "@karni/commerce-ui";
import { useParams } from "@tanstack/react-router";
import { SHOP_NAME } from "../shop/StoreLayout";

export default function Customer() {
  const { email } = useParams({ from: "/customers/$email" });
  return <CustomerPage email={decodeURIComponent(email)} siteName={SHOP_NAME} />;
}
