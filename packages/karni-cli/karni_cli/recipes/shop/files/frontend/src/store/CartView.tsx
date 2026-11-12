// The cart page: each line with its quantity, a way to take it out, the totals and checkout.
import {
  Button,
  EmptyState,
  ErrorState,
  Input,
  Skeleton,
  usePageMeta,
} from "@karni/ui";
import { Link, useRouter } from "@tanstack/react-router";
import { useCart, useSetQuantity } from "./cart";
import { ProductImageBox } from "./ProductCard";
import { Money } from "./Price";
import { SHOP_NAME } from "./StoreLayout";
import type { CartLine } from "./types";

function Line({ line }: { line: CartLine }) {
  const set = useSetQuantity();
  const change = (value: string) => {
    const quantity = Math.max(0, Math.floor(Number(value) || 0));
    if (quantity !== line.quantity)
      set.mutate({ product: line.product.id, quantity });
  };
  return (
    <li className="flex flex-wrap items-center gap-4 border-b border-border py-4">
      <div className="w-20">
        <ProductImageBox src={line.product.image} alt="" />
      </div>
      <div className="min-w-0 flex-1 space-y-1">
        <Link
          to="/shop/$slug"
          params={{ slug: line.product.slug }}
          className="font-medium hover:underline"
        >
          {line.product.name}
        </Link>
        <p className="text-sm text-muted-foreground">
          <Money value={line.unit_price} /> each
        </p>
        {line.problem ? (
          <p className="text-sm font-medium text-destructive">{line.problem}</p>
        ) : null}
      </div>
      <Input
        aria-label={`Quantity of ${line.product.name}`}
        type="number"
        min={0}
        className="w-20"
        defaultValue={line.quantity}
        key={line.quantity}
        onBlur={(event) => change(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") change(event.currentTarget.value);
        }}
      />
      <Money value={line.line_total} className="w-24 text-right font-medium" />
      <Button
        variant="ghost"
        onClick={() => set.mutate({ product: line.product.id, quantity: 0 })}
      >
        Remove<span className="sr-only"> {line.product.name}</span>
      </Button>
    </li>
  );
}

export function CartView() {
  const router = useRouter();
  const cart = useCart();
  usePageMeta({ title: "Your cart", siteName: SHOP_NAME });
  if (cart.isPending) return <Skeleton className="h-64 w-full" />;
  if (cart.isError)
    return (
      <ErrorState error={cart.error} onRetry={() => void cart.refetch()} />
    );
  const lines = cart.data.lines;
  if (lines.length === 0) {
    return (
      <EmptyState
        title="Your cart is empty"
        description="Find something you like in the shop."
        action={
          <Button onClick={() => router.history.push("/shop")}>
            Browse the shop
          </Button>
        }
      />
    );
  }
  return (
    <div className="space-y-6">
      <ul aria-label="Cart">
        {lines.map((line) => (
          <Line key={line.id} line={line} />
        ))}
      </ul>
      <div className="ml-auto max-w-sm space-y-3">
        <p className="flex justify-between text-lg font-semibold">
          Subtotal <Money value={cart.data.subtotal} />
        </p>
        <p className="text-sm text-muted-foreground">
          The total is worked out again when you check out.
        </p>
        <Button
          className="w-full"
          disabled={!cart.data.ready}
          onClick={() => router.history.push("/checkout")}
        >
          Check out
        </Button>
        {!cart.data.ready ? (
          <p className="text-sm text-destructive">
            Change the lines marked above to check out.
          </p>
        ) : null}
      </div>
    </div>
  );
}
