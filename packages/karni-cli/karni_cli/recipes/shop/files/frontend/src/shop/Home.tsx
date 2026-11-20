// The shop's front page: a welcome, the categories, featured products and what is new.
import { ItemImage } from "@karni/commerce-ui";
import {
  Button,
  EmptyState,
  Skeleton,
  useResourceList,
  usePageMeta,
} from "@karni/ui";
import { Link, useRouter } from "@tanstack/react-router";
import { ProductCard } from "./ProductCard";
import { useShopName } from "./name";
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
  const id = `shelf-${title.toLowerCase().replace(/\s+/g, "-")}`;
  return (
    <section aria-labelledby={id} className="space-y-3">
      <h2 id={id} className="text-xl font-semibold">
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
  const shopName = useShopName();
  const router = useRouter();
  usePageMeta({
    title: shopName,
    description: `${shopName}: browse the catalogue, add to the cart and pay online.`,
  });
  const categories = useResourceList<Category>("categories", {
    pageSize: 100,
  });
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
        <h1 className="text-3xl font-semibold">{shopName}</h1>
        <p className="mt-2 text-muted-foreground">
          Things for the kitchen, the garden, the desk and the road, made to
          last.
        </p>
        <Button
          className="mt-6"
          onClick={() => router.history.push("/shop/catalogue")}
        >
          Shop everything
        </Button>
      </section>
      <section aria-labelledby="categories" className="space-y-3">
        <h2 id="categories" className="text-xl font-semibold">
          Categories
        </h2>
        {categories.isPending ? (
          <Skeleton className="h-32 w-full" />
        ) : (
          <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
            {tops.map((category) => (
              <li key={category.id}>
                <Link
                  to="/shop/catalogue"
                  search={{ category: category.id }}
                  className="flex flex-col gap-2 rounded-lg border border-border p-2 hover:bg-muted"
                >
                  <ItemImage src={category.image} alt="" />
                  <span className="font-medium">{category.name}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
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
