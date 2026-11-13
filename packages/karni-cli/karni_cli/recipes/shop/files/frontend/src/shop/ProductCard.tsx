// A product in a grid: its picture, name, price, what is left and a button that adds one.
import { AddToCart, ItemImage, Money, PriceTag } from "@karni/commerce-ui";
import { Link } from "@tanstack/react-router";
import { Rating } from "./Rating";
import type { Product } from "./types";

/** In stock, a few left, or sold out, in words. */
export function StockState({ available }: { available: number }) {
  if (available <= 0) {
    return (
      <span className="text-sm font-medium text-destructive">Sold out</span>
    );
  }
  if (available <= 3) {
    return (
      <span className="text-sm text-muted-foreground">
        Only {available} left
      </span>
    );
  }
  return <span className="text-sm text-muted-foreground">In stock</span>;
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
          <StockState available={product.stock_left ?? 1} />
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
          <StockState available={product.stock_left ?? 1} />
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
