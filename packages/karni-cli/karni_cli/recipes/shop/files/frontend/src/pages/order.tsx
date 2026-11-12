// /orders/$number: one order, and the confirmation after paying (@karni/commerce-ui). A
// guest reads it with the key from checkout (?key=, the link in the email).
import { OrderPage as Order } from "@karni/commerce-ui";
import { useParams } from "@tanstack/react-router";
import { useSearchValues } from "../shop/search";
import { SHOP_NAME } from "../shop/StoreLayout";

export default function OrderPage() {
  const { number } = useParams({ from: "/orders/$number" });
  const search = useSearchValues();
  return (
    <Order
      number={number}
      orderKey={search.key ?? ""}
      justPaid={search.paid === "1"}
      siteName={SHOP_NAME}
    />
  );
}
