// A product's page: its pictures, price, stock, description, a quantity and Add to cart.
import {
  Button,
  EmptyState,
  ErrorState,
  Input,
  Label,
  Skeleton,
  useResourceList,
  usePageMeta,
} from "@karni/ui";
import { Link } from "@tanstack/react-router";
import { useId, useState } from "react";
import { ProductImageBox, useAddToCart } from "./ProductCard";
import { Price, StockState } from "./Price";
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
      <ProductImageBox
        src={current?.image ?? null}
        alt={current?.alt || product.name}
      />
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
                <ProductImageBox src={picture.image} alt="" />
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
  const add = useAddToCart();
  const [quantity, setQuantity] = useState(1);
  const quantityId = useId();
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
        action={<Link to="/shop">Back to the shop</Link>}
      />
    );
  }
  const soldOut = product.available <= 0;
  return (
    <article className="grid gap-8 md:grid-cols-2">
      <Gallery product={product} />
      <div className="space-y-4">
        <nav aria-label="Breadcrumb" className="text-sm text-muted-foreground">
          <Link to="/shop" className="hover:underline">
            Shop
          </Link>{" "}
          / {product.name}
        </nav>
        <h1 className="text-2xl font-semibold">{product.name}</h1>
        <Price
          price={product.price}
          current={product.current_price}
          onSale={product.on_sale}
          className="text-xl"
        />
        <StockState available={product.available} />
        {product.short_description ? <p>{product.short_description}</p> : null}
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex w-24 flex-col gap-1">
            <Label htmlFor={quantityId}>Quantity</Label>
            <Input
              id={quantityId}
              type="number"
              min={1}
              max={Math.max(product.available, 1)}
              value={quantity}
              disabled={soldOut}
              onChange={(event) =>
                setQuantity(Math.max(1, Number(event.target.value) || 1))
              }
            />
          </div>
          <Button disabled={soldOut} onClick={() => add(product, quantity)}>
            {soldOut ? "Sold out" : "Add to cart"}
          </Button>
        </div>
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
