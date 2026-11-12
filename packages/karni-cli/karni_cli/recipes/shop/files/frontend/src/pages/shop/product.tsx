// /shop/products/$slug: one product (shop/ProductView.tsx).
import { useParams } from "@tanstack/react-router";
import { ProductView } from "../../shop/ProductView";

export default function ProductPage() {
  const { slug } = useParams({ from: "/shop/products/$slug" });
  return <ProductView slug={slug} />;
}
