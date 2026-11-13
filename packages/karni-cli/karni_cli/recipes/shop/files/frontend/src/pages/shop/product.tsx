// /shop/catalogue/$slug: one product (shop/ProductView.tsx).
import { useParams } from "@tanstack/react-router";
import { ProductView } from "../../shop/ProductView";

export default function ProductPage() {
  const { slug } = useParams({ from: "/shop/catalogue/$slug" });
  return <ProductView slug={slug} />;
}
