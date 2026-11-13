// Products beside the one on the page: the related ones (staff's choice, then its
// category's) and the ones this browser looked at last.
import { useKarniClient, useResourceList } from "@karni/ui";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ProductCard } from "./ProductCard";
import { readRecent, rememberViewed } from "./recent";
import type { Product } from "./types";

function Row({ title, products }: { title: string; products: Product[] }) {
  if (products.length === 0) return null;
  return (
    <section
      aria-label={title}
      className="space-y-3 border-t border-border pt-6"
    >
      <h2 className="text-xl font-semibold">{title}</h2>
      <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {products.map((product) => (
          <li key={product.id} className="flex">
            <ProductCard product={product} />
          </li>
        ))}
      </ul>
    </section>
  );
}

export function RelatedProducts({ product }: { product: Product }) {
  const client = useKarniClient();
  const related = useQuery<Product[]>({
    queryKey: ["shop", "related", product.id],
    queryFn: ({ signal }) =>
      client.request<Product[]>(`/products/${product.id}/related/`, { signal }),
  });
  return <Row title="You may also like" products={related.data ?? []} />;
}

/** The products seen before this one (``current`` is remembered once shown). */
export function RecentlyViewed({ current }: { current?: string }) {
  const [ids] = useState(() =>
    readRecent()
      .filter((id) => id !== current)
      .slice(0, 4),
  );
  useEffect(() => {
    if (current) rememberViewed(current);
  }, [current]);
  const found = useResourceList<Product>(
    "products",
    { filters: { ids: ids.join(",") }, pageSize: 4 },
    { enabled: ids.length > 0 },
  );
  const products = (found.data?.results ?? [])
    .slice()
    .sort((a, b) => ids.indexOf(a.id) - ids.indexOf(b.id));
  return (
    <Row title="Recently viewed" products={ids.length > 0 ? products : []} />
  );
}
