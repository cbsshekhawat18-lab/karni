// /orders/$number/packing-slip: what goes in the parcel and where, for staff to print.
import { OrderDocumentPage } from "@karni/commerce-ui";
import { useParams } from "@tanstack/react-router";

export default function PackingSlip() {
  const { number } = useParams({ from: "/orders/$number/packing-slip" });
  return <OrderDocumentPage number={number} kind="packing_slip" />;
}
