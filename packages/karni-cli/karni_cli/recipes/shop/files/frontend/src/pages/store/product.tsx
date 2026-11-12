// /shop/$slug: one product (store/ProductView.tsx).
import { useParams } from "@tanstack/react-router";
import { ProductView } from "../../store/ProductView";

export default function ProductPage() {
  const { slug } = useParams({ from: "/shop/$slug" });
  return <ProductView slug={slug} />;
}
