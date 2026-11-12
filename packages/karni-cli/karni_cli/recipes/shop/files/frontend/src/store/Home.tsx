// The shop's front page: a welcome, the categories, featured products and what is new.
import {
  Button,
  EmptyState,
  Skeleton,
  useResourceList,
  usePageMeta,
} from "@karni/ui";
import { Link, useRouter } from "@tanstack/react-router";
import { ProductCard, ProductImageBox } from "./ProductCard";
import { SHOP_NAME } from "./StoreLayout";
import type { Category, Product } from "./types";

function Shelf({
  title,
  products,
  loading,
}: {
  title: string;
  products: Product[];
  loading: boolean;
}) {
  return (
    <section aria-labelledby={`shelf-${title}`} className="space-y-3">
      <h2 id={`shelf-${title}`} className="text-xl font-semibold">
        {title}
      </h2>
      {loading ? (
        <Skeleton className="h-64 w-full" />
      ) : products.length === 0 ? (
        <EmptyState title="Nothing here yet" headingLevel={3} />
      ) : (
        <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {products.map((product) => (
            <li key={product.id} className="flex">
              <ProductCard product={product} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function StoreHome() {
  const router = useRouter();
  usePageMeta({
    title: SHOP_NAME,
    description: `${SHOP_NAME}: browse the catalogue, add to the cart and pay online.`,
  });
  const categories = useResourceList<Category>("categories", { pageSize: 100 });
  const featured = useResourceList<Product>("products", {
    pageSize: 4,
    filters: { featured: true },
  });
  const fresh = useResourceList<Product>("products", {
    pageSize: 4,
    ordering: "-created_at",
  });
  const tops = (categories.data?.results ?? []).filter(
    (category) => category.parent === null,
  );
  return (
    <div className="space-y-10">
      <section className="rounded-lg bg-muted px-6 py-10">
        <h1 className="text-3xl font-semibold">{SHOP_NAME}</h1>
        <p className="mt-2 max-w-xl text-muted-foreground">
          Things for the kitchen, the garden, the desk and the road, made to
          last.
        </p>
        <Button className="mt-6" onClick={() => router.history.push("/shop")}>
          Shop everything
        </Button>
      </section>
      <section aria-labelledby="categories" className="space-y-3">
        <h2 id="categories" className="text-xl font-semibold">
          Categories
        </h2>
        <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
          {tops.map((category) => (
            <li key={category.id}>
              <Link
                to="/shop"
                search={{ category: category.id }}
                className="flex flex-col gap-2 rounded-lg border border-border p-2 hover:bg-muted"
              >
                <ProductImageBox src={category.image} alt="" />
                <span className="font-medium">{category.name}</span>
              </Link>
            </li>
          ))}
        </ul>
      </section>
      <Shelf
        title="Featured"
        products={featured.data?.results ?? []}
        loading={featured.isPending}
      />
      <Shelf
        title="New arrivals"
        products={fresh.data?.results ?? []}
        loading={fresh.isPending}
      />
    </div>
  );
}
