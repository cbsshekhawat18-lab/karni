// /order/$number: an order's page, the confirmation after payment (store/OrderView.tsx).
import { useParams } from "@tanstack/react-router";
import { OrderView } from "../../store/OrderView";
import { useSearchValues } from "../../store/search";

export default function OrderPage() {
  const { number } = useParams({ from: "/order/$number" });
  const search = useSearchValues();
  return (
    <OrderView
      number={number}
      orderKey={search.key ?? ""}
      justPaid={search.paid === "1"}
    />
  );
}
