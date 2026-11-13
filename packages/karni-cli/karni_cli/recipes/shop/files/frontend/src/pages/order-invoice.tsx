// /orders/$number/invoice: the order's invoice, to print or save as PDF. Its buyer, a guest
// with the key from checkout (?key=) and staff may open it (@karni/commerce-ui).
import { OrderDocumentPage } from "@karni/commerce-ui";
import { useParams } from "@tanstack/react-router";
import { useSearchValues } from "../shop/search";

export default function Invoice() {
  const { number } = useParams({ from: "/orders/$number/invoice" });
  const search = useSearchValues();
  return <OrderDocumentPage number={number} orderKey={search.key ?? ""} kind="invoice" />;
}
