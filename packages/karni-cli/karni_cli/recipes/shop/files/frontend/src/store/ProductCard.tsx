// A product in a grid: its picture, name, price, stock and a button to add one to the cart.
import { Button } from "@karni/ui";
import { Link } from "@tanstack/react-router";
import { useSetQuantity, useCart } from "./cart";
import { Price, StockState } from "./Price";
import type { Product } from "./types";

export function ProductImageBox({
  src,
  alt,
}: {
  src: string | null;
  alt: string;
}) {
  return src ? (
    <img
      src={src}
      alt={alt}
      loading="lazy"
      className="aspect-square w-full rounded-md object-cover"
    />
  ) : (
    <div
      aria-hidden="true"
      className="aspect-square w-full rounded-md bg-muted"
    />
  );
}

/** One more of ``product`` in the cart (or the first), with a short note when it went in. */
export function useAddToCart(): (
  product: { id: string; name: string },
  quantity?: number,
) => void {
  const set = useSetQuantity();
  const cart = useCart();
  return (product, quantity = 1) => {
    const held =
      cart.data?.lines.find((line) => line.product.id === product.id)
        ?.quantity ?? 0;
    set.mutate({ product: product.id, quantity: held + quantity });
  };
}

export function ProductCard({ product }: { product: Product }) {
  const add = useAddToCart();
  return (
    <article className="flex w-full flex-col gap-3 rounded-lg border border-border bg-card p-3 text-card-foreground">
      <Link
        to="/shop/$slug"
        params={{ slug: product.slug }}
        className="flex flex-col gap-3"
      >
        <ProductImageBox src={product.image} alt="" />
        <h3 className="font-medium">{product.name}</h3>
      </Link>
      <Price
        price={product.price}
        current={product.current_price}
        onSale={product.on_sale}
      />
      <StockState available={product.available} />
      <Button
        className="mt-auto"
        disabled={product.available <= 0}
        onClick={() => add(product)}
        aria-label={`Add ${product.name} to the cart`}
      >
        {product.available <= 0 ? "Sold out" : "Add to cart"}
      </Button>
    </article>
  );
}
