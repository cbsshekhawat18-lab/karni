// A product's page: its pictures, price, what is left, description, and Add to cart.
import { AddToCart, ItemImage, PriceTag } from "@karni/commerce-ui";
import {
  Button,
  EmptyState,
  ErrorState,
  Skeleton,
  useResourceList,
  usePageMeta,
} from "@karni/ui";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { StockState } from "./ProductCard";
import { SHOP_NAME } from "./StoreLayout";
import type { Product } from "./types";

function Gallery({ product }: { product: Product }) {
  const pictures = [
    ...(product.image ? [{ image: product.image, alt: product.name }] : []),
    ...product.gallery,
  ];
  const [shown, setShown] = useState(0);
  const current = pictures[shown];
  return (
    <div className="space-y-3">
      <ItemImage src={current?.image} alt={current?.alt || product.name} />
      {pictures.length > 1 ? (
        <ul className="flex flex-wrap gap-2" aria-label="More pictures">
          {pictures.map((picture, index) => (
            <li key={picture.image} className="w-16">
              <Button
                variant="ghost"
                className="h-auto w-16 p-1"
                aria-label={`Show picture ${index + 1}`}
                aria-pressed={index === shown}
                onClick={() => setShown(index)}
              >
                <ItemImage src={picture.image} alt="" />
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function ProductView({ slug }: { slug: string }) {
  const found = useResourceList<Product>("products", {
    filters: { slug },
    pageSize: 1,
  });
  const product = found.data?.results[0];
  usePageMeta({
    title: product?.name ?? "Product",
    siteName: SHOP_NAME,
    description: product?.short_description || product?.name,
  });
  if (found.isPending) return <Skeleton className="h-96 w-full" />;
  if (found.isError)
    return (
      <ErrorState error={found.error} onRetry={() => void found.refetch()} />
    );
  if (!product) {
    return (
      <EmptyState
        title="This product is not here"
        description="It may have sold out for good, or the link is old."
        action={<Link to="/shop/products">Back to the products</Link>}
      />
    );
  }
  return (
    <article className="grid gap-8 md:grid-cols-2">
      <Gallery product={product} />
      <div className="space-y-4">
        <nav aria-label="Breadcrumb" className="text-sm text-muted-foreground">
          <Link to="/shop/products" className="hover:underline">
            Products
          </Link>{" "}
          / {product.name}
        </nav>
        <h1 className="text-2xl font-semibold">{product.name}</h1>
        <PriceTag
          price={product.current_price}
          compareAt={product.on_sale ? product.price : null}
          className="text-xl"
        />
        <StockState available={product.available} />
        {product.short_description ? <p>{product.short_description}</p> : null}
        <AddToCart
          kind="product"
          item={product.id}
          name={product.name}
          available={product.available}
        />
        <p className="text-sm text-muted-foreground">SKU {product.sku}</p>
        {product.description ? (
          <div className="space-y-2 whitespace-pre-line border-t border-border pt-4">
            {product.description}
          </div>
        ) : null}
      </div>
    </article>
  );
}
