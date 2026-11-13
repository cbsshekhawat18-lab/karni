// /orders/$number: for staff the order to run (refunds, the parcel, notes, history), for
// its buyer the order and the confirmation after paying (@karni/commerce-ui). A guest
// reads it with the key from checkout (?key=, the link in the email).
import { OrderPage as Order, StaffOrderPage } from "@karni/commerce-ui";
import { useParams } from "@tanstack/react-router";
import { useSearchValues } from "../shop/search";
import { useShopName } from "../shop/StoreLayout";
import { usePerson } from "../shop/staff";

export default function OrderPage() {
  const shopName = useShopName();
  const { number } = useParams({ from: "/orders/$number" });
  const search = useSearchValues();
  const person = usePerson();
  if (person === "loading") return null;
  if (person === "staff") return <StaffOrderPage number={number} siteName={shopName} />;
  return (
    <Order
      number={number}
      orderKey={search.key ?? ""}
      justPaid={search.paid === "1"}
      siteName={shopName}
    />
  );
}
