// /reports: sales by date, item, category and coupon, and the stock, each with a CSV
// file (@karni/commerce-ui, the reports of karni-commerce and shop/reports.py).
import { ReportsPage } from "@karni/commerce-ui";
import { useShopName } from "../shop/name";

export default function Reports() {
  return <ReportsPage siteName={useShopName()} />;
}
