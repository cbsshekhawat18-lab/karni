// A product in a grid: its picture, name, price, what is left and a button that adds one.
import { AddToCart, ItemImage, Money, PriceTag } from "@karni/commerce-ui";
import { Link } from "@tanstack/react-router";
import { Rating } from "./Rating";
import type { Product } from "./types";

/**
 * In stock, a few left, or sold out, in words. `left` is null when the shop does not
 * show the figure (Settings, Shop) or it never runs out; `low` says it runs low at
 * the shop's level. A file is a download, never out of stock.
 */
export function StockState({
  left,
  low = false,
  digital = false,
}: {
  left: number | null;
  low?: boolean;
  digital?: boolean;
}) {
  if (digital) {
    return <span className="text-sm text-muted-foreground">Digital download</span>;
  }
  if (left !== null && left <= 0) {
    return <span className="text-sm font-medium text-destructive">Sold out</span>;
  }
  if (low) {
    return (
      <span className="text-sm text-muted-foreground">
        {left !== null ? `Only ${left} left` : "Running low"}
      </span>
    );
  }
  return <span className="text-sm text-muted-foreground">In stock</span>;
}

/** A product's stock in words, from what the API says of it. */
export function ProductStock({ product }: { product: Product }) {
  return (
    <StockState left={product.stock_left} low={product.runs_low} digital={product.digital} />
  );
}

export function ProductCard({ product }: { product: Product }) {
  return (
    <article className="flex w-full flex-col gap-3 rounded-lg border border-border bg-card p-3 text-card-foreground">
      <Link
        to="/shop/products/$slug"
        params={{ slug: product.slug }}
        className="flex flex-col gap-3"
      >
        <ItemImage src={product.image} alt="" />
        <h3 className="font-medium">{product.name}</h3>
      </Link>
      <Rating average={product.rating_average} count={product.rating_count} />
      {product.variations.length > 0 ? (
        <>
          <span className="font-semibold">
            {product.price_from === product.price_to ? (
              <Money value={product.price_from} />
            ) : (
              <>
                From <Money value={product.price_from} />
              </>
            )}
          </span>
          <ProductStock product={product} />
          <Link
            to="/shop/products/$slug"
            params={{ slug: product.slug }}
            className="mt-auto inline-flex h-9 items-center justify-center rounded-md border border-input px-3 text-sm font-medium hover:bg-accent"
          >
            Choose options<span className="sr-only"> of {product.name}</span>
          </Link>
        </>
      ) : (
        <>
          <PriceTag
            price={product.current_price}
            compareAt={product.on_sale ? product.price : null}
          />
          <ProductStock product={product} />
          <AddToCart
            className="mt-auto"
            kind="product"
            item={product.id}
            name={product.name}
            available={product.stock_left}
            quantity={false}
          />
        </>
      )}
    </article>
  );
}
